"""Linux storage-side snapshot sealing, retention and isolated restore drills.

This module is also sent over pinned SSH as source. It has no agent imports,
does not execute restored content, and emits only a small credential-free result.
"""
from __future__ import annotations

import fcntl
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager

MANIFEST = "snapshot.manifest.json"
INVENTORY = ".rsync-boy.inventory.jsonl"
MAX_MANIFEST_BYTES = 128 * 1024 * 1024
SEAL_LIMITS = {"max_entries": 250000, "max_bytes": 1024 ** 4,
               "timeout_sec": 3600, "min_free_bytes": 0}


def checked_root(value, *, create=False):
    path = Path(value)
    if not path.is_absolute() or path == Path("/") or ".." in path.parts:
        raise ValueError("Storage roots must be absolute non-root paths")
    # Never resolve a symlink and then operate on the redirected destination.
    for parent in reversed((path, *path.parents)):
        if parent.is_symlink():
            raise ValueError("Storage path contains a symbolic link")
        if parent.exists():
            info = parent.stat()
            if info.st_uid not in {0, os.geteuid()} or (
                    stat.S_IMODE(info.st_mode) & 0o022 and not info.st_mode & stat.S_ISVTX):
                raise ValueError("Storage path has an untrusted writable ancestor")
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.resolve(strict=True) != path or not path.is_dir():
        raise ValueError("Storage root is not a canonical directory")
    info = path.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise ValueError("Storage root must be owned by this account and not writable by others")
    return path


@contextmanager
def retention_lock(root):
    path = root / ".rsync-boy.retention.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise ValueError("Unsafe retention lock")
        os.fchmod(descriptor, 0o600)
        # A busy drill/retention pass fails promptly; the scheduler retries later.
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def snapshot_pattern(prefix):
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", prefix):
        raise ValueError("Invalid snapshot prefix")
    return re.compile(rf"{re.escape(prefix)}_\d{{8}}_\d{{6}}")


def select_snapshot(root, prefix, name):
    if name == "latest":
        latest = root / "latest"
        if not latest.is_symlink():
            raise ValueError("Latest snapshot must be a relative symbolic link")
        name = os.readlink(latest)
    if not isinstance(name, str) or not snapshot_pattern(prefix).fullmatch(name):
        raise ValueError("Snapshot is not a completed dated snapshot")
    selected = root / name
    if selected.is_symlink() or not selected.is_dir():
        raise ValueError("Completed snapshot is unavailable")
    return selected


def secure_staging(request):
    root = checked_root(request["snapshot_root"])
    name = request["snapshot"]
    if not snapshot_pattern(request["snapshot_prefix"]).fullmatch(name):
        raise ValueError("Invalid snapshot staging name")
    staging = root / (name + ".partial")
    if staging.is_symlink() or not staging.is_dir():
        raise ValueError("Invalid snapshot staging directory")
    # Archive-mode rsync can set the receiving directory's owner when running
    # as root. Only this generated container belongs to the storage account;
    # ownership and modes of backed-up entries remain unchanged.
    if os.geteuid() == 0:
        os.chown(staging, os.geteuid(), os.getegid())
    if staging.stat().st_uid != os.geteuid():
        raise ValueError("Snapshot staging belongs to another account")
    os.chmod(staging, 0o700)
    return {"secured": True}


def prepare_root(request):
    checked_root(request["snapshot_root"], create=True)
    return {"prepared": True}


def plain_file(path, max_bytes):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            raise ValueError("Invalid or oversized snapshot metadata")
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def digest_file(path, info):
    digest = hashlib.sha256()
    with plain_file(path, SEAL_LIMITS["max_bytes"]) as handle:
        before = os.fstat(handle.fileno())
        if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("Snapshot entry changed during verification")
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
        after = os.fstat(handle.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("Snapshot file changed during verification")
    return digest.hexdigest()


def tree_records(root, limits, *, independent_from=None):
    counts = {"entries": 0, "files": 0, "bytes": 0}

    def walk(directory):
        if directory.is_symlink() or directory.resolve(strict=True) != directory:
            raise ValueError("Snapshot directory changed or contains an unsafe ancestor")
        with os.scandir(directory) as scan:
            children = []
            for child in scan:
                if len(children) >= limits["max_entries"]:
                    raise ValueError("Snapshot directory exceeds entry limit")
                children.append(child)
        for child in sorted(children, key=lambda item: item.name):
            path = Path(child.path)
            relative = path.relative_to(root).as_posix()
            if relative in {MANIFEST, INVENTORY}:
                continue
            info = path.lstat()
            counts["entries"] += 1
            if counts["entries"] > limits["max_entries"]:
                raise ValueError("Snapshot exceeds entry limit")
            record = {"path": relative}
            if stat.S_ISLNK(info.st_mode):
                record.update(kind="symlink", target=os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                record.update(kind="directory", mode=stat.S_IMODE(info.st_mode),
                              mtime=int(info.st_mtime))
            elif stat.S_ISREG(info.st_mode):
                counts["files"] += 1
                counts["bytes"] += info.st_size
                if counts["bytes"] > limits["max_bytes"]:
                    raise ValueError("Snapshot exceeds byte limit")
                if independent_from is not None:
                    original = (independent_from / relative).lstat()
                    if (info.st_dev, info.st_ino) == (original.st_dev, original.st_ino):
                        raise ValueError("Restored file is hard-linked to the backup")
                record.update(kind="file", mode=stat.S_IMODE(info.st_mode),
                              mtime=int(info.st_mtime), size=info.st_size,
                              sha256=digest_file(path, info))
            else:
                raise ValueError("Special files are outside this restore drill's coverage")
            yield record
            if record["kind"] == "directory":
                yield from walk(path)

    return walk(root), counts


def seal(request):
    staging = checked_root(request["staging"])
    with plain_file(staging / MANIFEST, 65536) as handle:
        manifest = json.load(handle)
    inventory = staging / INVENTORY
    # 'x' prevents replacing source content or a pre-existing hard-linked file.
    digest = hashlib.sha256()
    records, counts = tree_records(staging, SEAL_LIMITS)
    total = 0
    with inventory.open("xb") as handle:
        os.chmod(inventory, 0o600)
        for record in records:
            line = (json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
            total += len(line)
            if total > MAX_MANIFEST_BYTES:
                raise ValueError("Snapshot inventory exceeds size limit")
            digest.update(line)
            handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    manifest.update(schema_version=2, finished_at=int(time.time()),
                    inventory={"file": INVENTORY, "sha256": digest.hexdigest(),
                    "entries": counts["entries"], "files": counts["files"],
                    "bytes": counts["bytes"]})
    write_json(staging / MANIFEST, manifest)
    return {"sealed": True, **counts}


def write_json(path, document):
    descriptor, temporary = tempfile.mkstemp(prefix=".rsync-boy-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def inventory_records(path):
    with plain_file(path, MAX_MANIFEST_BYTES) as handle:
        for line in handle:
            if len(line) > 65536:
                raise ValueError("Oversized snapshot inventory entry")
            yield json.loads(line)


def verify(tree, snapshot, manifest, limits, *, independent=False):
    inventory = snapshot / INVENTORY
    with plain_file(inventory, MAX_MANIFEST_BYTES) as handle:
        hasher = hashlib.sha256()
        while chunk := handle.read(1024 * 1024):
            hasher.update(chunk)
        digest = hasher.hexdigest()
    expected = manifest["inventory"]
    if expected.get("file") != INVENTORY or digest != expected.get("sha256"):
        raise ValueError("Snapshot inventory checksum mismatch")
    actual, counts = tree_records(tree, limits, independent_from=snapshot if independent else None)
    for wanted, found in itertools.zip_longest(inventory_records(inventory), actual):
        if wanted != found:
            raise ValueError("Restored content or recorded metadata differs from the snapshot inventory")
    if any(counts[key] != expected.get(key) for key in ("entries", "files", "bytes")):
        raise ValueError("Snapshot inventory totals mismatch")
    return counts


def run_copy(snapshot, destination, seconds):
    # No --link-dest: restored files must have independent inodes. Never follow
    # symlinks, run programs, or restore into an operator-supplied live directory.
    process = subprocess.Popen(["rsync", "-a", "-H", "--numeric-ids",
                                "--exclude=/" + MANIFEST, "--exclude=/" + INVENTORY,
                                "--", str(snapshot) + "/", str(destination) + "/"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    try:
        process.wait(timeout=seconds)
        if process.returncode:
            raise RuntimeError("Isolated restore copy failed")
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def cleanup(directory, root):
    if not os.path.lexists(directory):
        return
    if directory.parent != root or directory.is_symlink() or directory.resolve() != directory:
        raise ValueError("Refusing unsafe restore cleanup")
    # rsync may restore restrictive directory modes. Alter only independent
    # scratch directories so that this account can remove its own test copy.
    for current, dirs, _ in os.walk(directory, followlinks=False):
        os.chmod(current, 0o700)
        for name in dirs:
            child = Path(current) / name
            if not child.is_symlink():
                os.chmod(child, 0o700)
    shutil.rmtree(directory)


def drill(request):
    limits = request["limits"]
    root = checked_root(request["snapshot_root"])
    restore = Path(request["restore_root"])
    source = Path(request["source_path"])
    sources = (source, source.resolve(strict=True)) if source.exists() else (source,)
    for other in (root, *sources):
        if restore == other or restore in other.parents or other in restore.parents:
            raise ValueError("Restore root must be separate from source and snapshot trees")
    restore = checked_root(str(restore), create=True)
    if stat.S_IMODE(restore.stat().st_mode) != 0o700:
        raise ValueError("Restore root must have mode 0700")
    job_id = request["job_id"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", job_id):
        raise ValueError("Invalid drill id")
    report = {"kind": "filesystem_restore_drill", "job_id": job_id,
              "backup_job_id": request["backup_job_id"], "started_at": time.time(),
              "backup_definition_hash": request["backup_definition_hash"],
              "drill_definition_hash": request["drill_definition_hash"], "snapshot_root": str(root),
              "result": "error", "coverage": "files_sha256_types_symlinks_modes_mtime",
              "application_recovery_verified": False}
    destination = None
    report_path = restore / f"drill_{job_id}_{uuid.uuid4().hex}.json"
    started = time.monotonic()
    try:
        with retention_lock(root):
            snapshot = select_snapshot(root, request["snapshot_prefix"], request["snapshot"])
            report["snapshot"] = snapshot.name
            with plain_file(snapshot / MANIFEST, 65536) as handle:
                manifest = json.load(handle)
            if (manifest.get("schema_version") != 2 or manifest.get("job_id") != request["backup_job_id"]
                    or manifest.get("backup_definition_hash") != request["backup_definition_hash"]
                    or manifest.get("snapshot") != snapshot.name or not isinstance(manifest.get("inventory"), dict)):
                raise ValueError("Snapshot has no matching sealed inventory; create a new backup first")
            expected = manifest["inventory"]
            for key, bound in (("entries", limits["max_entries"]), ("bytes", limits["max_bytes"])):
                value = expected.get(key)
                if type(value) is not int or not 0 <= value <= bound:
                    raise ValueError("Snapshot exceeds this drill's limits")
            if shutil.disk_usage(restore).free < expected["bytes"] + limits["min_free_bytes"]:
                raise ValueError("Insufficient free space for an independent restore")
            verify(snapshot, snapshot, manifest, limits)
            destination = restore / f"drill_{job_id}_{uuid.uuid4().hex}.partial"
            destination.mkdir(mode=0o700)
            remaining = max(1, limits["timeout_sec"] - (time.monotonic() - started))
            run_copy(snapshot, destination, remaining)
            counts = verify(destination, snapshot, manifest, limits, independent=True)
            report.update(verified_entries=counts["entries"], verified_files=counts["files"],
                          verified_bytes=counts["bytes"])
            cleanup(destination, restore)
            destination = None
            report["result"] = "ok"
    except Exception as exc:
        # Do not emit restored contents, file names or exception text in telemetry.
        report["error_code"] = (
            "SNAPSHOT_BUSY" if isinstance(exc, BlockingIOError) else
            "TIMEOUT" if isinstance(exc, TimeoutError) else
            "PERMISSION_DENIED" if isinstance(exc, PermissionError) else
            "MISSING_PATH" if isinstance(exc, FileNotFoundError) else
            "VALIDATION_FAILED" if isinstance(exc, ValueError) else "RESTORE_FAILED"
        )
        if isinstance(exc, ValueError):
            report["detail"] = str(exc)[:256]
    finally:
        signal.alarm(20)  # Give safe cleanup a separate bounded grace period.
        if destination is not None:
            try:
                cleanup(destination, restore)
            except Exception:
                report.update(result="error", cleanup_required=True, scratch_directory=destination.name)
        report["finished_at"] = time.time()
        report["report_path"] = str(report_path)
        signal.alarm(0)
        write_json(report_path, report)
        write_json(restore / f"drill_{job_id}.latest.json", report)
        # Retain thirty immutable receipts, including prior successful drills.
        pattern = re.compile(rf"drill_{re.escape(job_id)}_[a-f0-9]{{32}}\.json")
        receipts = sorted((path for path in restore.iterdir() if pattern.fullmatch(path.name)
                           and not path.is_symlink() and path.is_file()),
                          key=lambda path: path.stat().st_mtime, reverse=True)
        for old in receipts[30:]:
            old.unlink()
    return report


def prune(request):
    root = checked_root(request["snapshot_root"])
    prefix = request["snapshot_prefix"]
    cutoff = time.time() - int(request["keep_days"]) * 86400
    if int(request["keep_days"]) <= 0:
        return {"pruned": 0}
    removed = 0
    try:
        with retention_lock(root):
            latest = select_snapshot(root, prefix, "latest")
            for path in root.iterdir():
                if (snapshot_pattern(prefix).fullmatch(path.name) and path != latest
                        and not path.is_symlink() and path.is_dir() and path.stat().st_mtime < cutoff):
                    shutil.rmtree(path)
                    removed += 1
    except BlockingIOError:
        return {"pruned": 0, "prune_deferred": True}
    return {"pruned": removed}


def main():
    os.umask(0o077)
    request = json.loads(sys.stdin.buffer.read(65537))
    seconds = int(request.get("limits", SEAL_LIMITS)["timeout_sec"])
    def expired(*_):
        raise TimeoutError("Storage operation exceeded its deadline")
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)
    action = request["action"]
    result = {"seal": seal, "drill": drill, "prune": prune,
              "secure_staging": secure_staging, "prepare_root": prepare_root}[action](request)
    signal.alarm(0)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"result": "error", "error_code": type(error).__name__}))
        sys.exit(1)
