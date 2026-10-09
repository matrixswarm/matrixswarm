"""Timestamped, hard-linked filesystem snapshots for RsyncBoy."""

from __future__ import annotations

import json
import os
import posixpath
import re
import shlex
import shutil
import tempfile
import time
from pathlib import Path

from rsync_boy.factory.ssh_transport import SSHTransport, parse_ssh_profile
from rsync_boy.factory.filesystem.storage_runner import storage_operation


_SAFE_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RsyncSnapshotJob:
    """Create a versioned snapshot by pushing to or pulling from an SSH host."""

    def __init__(self, log, shared):
        self.log = log
        self.shared = shared
        self.ctx = shared.get("context", {}) or {}
        self.job_id = self.ctx.get("job_id") or "filesystem_snapshot"

    def run(self):
        started = time.time()
        manifest_path = None
        try:
            cfg = self.ctx.get("config", {}) or {}
            job = self._validate_and_normalize_cfg(cfg)
            profile = parse_ssh_profile(cfg)
            stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
            snapshot_name = f"{job['snapshot_prefix']}_{stamp}"

            with SSHTransport(profile) as transport:
                if job["source_via_ssh"]:
                    snapshot_path, manifest_path = self._pull_snapshot(
                        transport, job, snapshot_name, started
                    )
                else:
                    snapshot_path, manifest_path = self._push_snapshot(
                        transport, job, snapshot_name, started
                    )

            self.shared["result"] = "ok"
            self.shared["snapshot"] = snapshot_path
            self.shared["finished_at"] = time.time()
            self.log(
                f"[FILESYSTEM][{self.job_id}] Completed snapshot "
                f"{snapshot_name} in {int(time.time() - started)}s"
            )
        except Exception as exc:
            self.shared["result"] = "error"
            self.shared["error"] = str(exc)
            self.shared["finished_at"] = time.time()
            self.log(f"[FILESYSTEM][{self.job_id}][ERROR] {exc}", level="ERROR")
            raise
        finally:
            if manifest_path:
                try:
                    os.remove(manifest_path)
                except OSError:
                    pass

    def _rsync_options(self, job, latest_exists):
        options = ["-a", "--numeric-ids", "--partial"]
        if job["preserve_hard_links"]:
            options.append("-H")
        if job["preserve_acls"]:
            options.append("-A")
        if job["preserve_xattrs"]:
            options.append("-X")
        if job["link_dest"] and latest_exists:
            options.append("--link-dest=../latest")
        for pattern in job["exclude"]:
            options += ["--exclude", pattern]
        return options

    def _push_snapshot(self, transport, job, snapshot_name, started):
        snapshot_path = f"{job['remote_path']}/{snapshot_name}"
        staging_path = f"{snapshot_path}.partial"
        latest_path = f"{job['remote_path']}/latest"
        self.log(
            f"[FILESYSTEM][{self.job_id}] Pushing snapshot "
            f"{job['source_path']} -> {snapshot_path}"
        )
        storage_operation({"action": "prepare_root", "snapshot_root": job["remote_path"]}, transport)
        if transport.path_exists(snapshot_path) or transport.path_exists(staging_path):
            raise RuntimeError(f"Snapshot already exists: {snapshot_path}")
        transport.run(f"mkdir -- {shlex.quote(staging_path)}")
        manifest_path = None
        try:
            options = self._rsync_options(job, transport.path_exists(latest_path))
            source = job["source_path"].rstrip("/") + "/"
            transport.rsync(source, staging_path.rstrip("/") + "/", options)
            storage_operation({"action": "secure_staging", "snapshot_root": job["remote_path"],
                               "snapshot_prefix": job["snapshot_prefix"], "snapshot": snapshot_name}, transport)

            for reserved in ("snapshot.manifest.json", ".rsync-boy.inventory.jsonl"):
                target = shlex.quote(staging_path + "/" + reserved)
                transport.run(f"test ! -e {target} && test ! -L {target}")

            manifest_path = self._write_manifest(
                job, snapshot_name, started, time.time()
            )
            transport.rsync(
                manifest_path,
                staging_path.rstrip("/") + "/snapshot.manifest.json",
                ["-a"],
            )
            if job["verify_manifest"]:
                storage_operation({"action": "seal", "staging": staging_path}, transport)

            root = shlex.quote(job["remote_path"])
            staging = shlex.quote(f"{snapshot_name}.partial")
            name = shlex.quote(snapshot_name)
            transport.run(
                f"cd -- {root} && "
                f"mv -- {staging} {name} && "
                f"touch -- {name} && "
                "rm -f -- .latest.new && "
                f"ln -s -- {name} .latest.new && "
                "mv -Tf -- .latest.new latest"
            )
            self._prune_remote(transport, job)
            return snapshot_path, manifest_path
        except Exception:
            transport.run(
                f"rm -rf -- {shlex.quote(staging_path)}",
                check=False,
            )
            if manifest_path:
                os.unlink(manifest_path)
            raise

    def _pull_snapshot(self, transport, job, snapshot_name, started):
        root = Path(job["remote_path"])
        snapshot_path = root / snapshot_name
        staging_path = root / f"{snapshot_name}.partial"
        latest_path = root / "latest"
        pending_latest = root / ".latest.new"
        self.log(
            f"[FILESYSTEM][{self.job_id}] Pulling snapshot "
            f"ssh:{job['source_path']} -> {snapshot_path}"
        )
        if os.path.lexists(snapshot_path) or os.path.lexists(staging_path):
            raise RuntimeError(f"Snapshot already exists: {snapshot_path}")

        staging_path.mkdir(mode=0o700)
        manifest_path = None
        try:
            options = self._rsync_options(
                job, self._safe_local_latest_exists(root, latest_path, job)
            )
            source = job["source_path"].rstrip("/") + "/"
            transport.rsync_from(source, str(staging_path) + os.sep, options)
            storage_operation({"action": "secure_staging", "snapshot_root": str(root),
                               "snapshot_prefix": job["snapshot_prefix"], "snapshot": snapshot_name})
            os.utime(staging_path)
            if any(os.path.lexists(staging_path / name) for name in
                   ("snapshot.manifest.json", ".rsync-boy.inventory.jsonl")):
                raise ValueError("Source contains reserved RsyncBoy manifest names")

            manifest_path = self._write_manifest(
                job, snapshot_name, started, time.time()
            )
            local_manifest = staging_path / "snapshot.manifest.json"
            shutil.copyfile(manifest_path, local_manifest)
            os.chmod(local_manifest, 0o600)
            if job["verify_manifest"]:
                storage_operation({"action": "seal", "staging": str(staging_path)})

            os.replace(staging_path, snapshot_path)
            if os.path.lexists(pending_latest):
                pending_latest.unlink()
            os.symlink(snapshot_name, pending_latest, target_is_directory=True)
            os.replace(pending_latest, latest_path)
            self._prune_local(job)
            return str(snapshot_path), manifest_path
        except Exception:
            if staging_path.exists() and staging_path.parent == root:
                shutil.rmtree(staging_path)
            if os.path.lexists(pending_latest):
                pending_latest.unlink()
            if manifest_path:
                os.unlink(manifest_path)
            raise

    @staticmethod
    def _safe_local_latest_exists(root: Path, latest_path: Path, job) -> bool:
        if not os.path.lexists(latest_path):
            return False
        if not latest_path.is_symlink():
            raise RuntimeError(f"Refusing unsafe non-symlink latest path: {latest_path}")
        target = os.readlink(latest_path)
        pattern = re.compile(
            rf"^{re.escape(job['snapshot_prefix'])}_\d{{8}}_\d{{6}}$"
        )
        if Path(target).name != target or not pattern.fullmatch(target):
            raise RuntimeError(f"Refusing unsafe latest snapshot target: {target}")
        return (root / target).is_dir()

    def _validate_and_normalize_cfg(self, cfg: dict) -> dict:
        source_via_ssh = bool(cfg.get("source_via_ssh", False))
        source_path = str(cfg.get("source_path") or "").strip()
        remote_path = str(cfg.get("remote_path") or "").strip().rstrip("/")
        prefix = str(cfg.get("snapshot_prefix") or self.job_id).strip()
        keep_days = int((cfg.get("remote_prune") or {}).get("keep_days", 14))

        if source_via_ssh:
            if not source_path.startswith("/") or source_path == "/":
                raise ValueError(
                    "config.source_path must be an absolute non-root SSH path"
                )
            if not os.path.isabs(remote_path) or os.path.abspath(remote_path) == os.path.abspath(os.sep):
                raise ValueError(
                    "config.remote_path must be an absolute non-root local path"
                )
        else:
            if not source_path or not os.path.isabs(source_path):
                raise ValueError("config.source_path must be an absolute local path")
            if not os.path.isdir(source_path):
                raise ValueError(f"config.source_path is not a directory: {source_path}")
            if not remote_path.startswith("/") or remote_path == "/":
                raise ValueError(
                    "config.remote_path must be an absolute non-root SSH path"
                )
        if not _SAFE_PREFIX.fullmatch(prefix):
            raise ValueError("config.snapshot_prefix contains unsafe characters")
        if not 0 <= keep_days <= 3650:
            raise ValueError("config.remote_prune.keep_days must be between 0 and 3650")

        excludes = cfg.get("exclude", [])
        if isinstance(excludes, str):
            excludes = [item.strip() for item in excludes.replace("\n", ",").split(",")]
        excludes = [str(item).strip() for item in excludes if str(item).strip()]

        if source_via_ssh:
            source_path = posixpath.normpath(source_path)
            remote_path = os.path.abspath(remote_path)
            if os.path.lexists(remote_path) and os.path.islink(remote_path):
                raise ValueError("config.remote_path must not be a symbolic link")
            storage_operation({"action": "prepare_root", "snapshot_root": remote_path})
        else:
            source_path = os.path.abspath(source_path)

        return {
            "source_via_ssh": source_via_ssh,
            "source_path": source_path,
            "remote_path": remote_path,
            "snapshot_prefix": prefix,
            "exclude": excludes,
            "link_dest": bool(cfg.get("link_dest", True)),
            "preserve_hard_links": bool(cfg.get("preserve_hard_links", True)),
            "preserve_acls": bool(cfg.get("preserve_acls", True)),
            "preserve_xattrs": bool(cfg.get("preserve_xattrs", True)),
            "verify_manifest": bool(cfg.get("verify_manifest", False)),
            "remote_prune": {"keep_days": keep_days},
        }

    def _write_manifest(self, job, snapshot_name, started, finished):
        manifest = {
            "job_id": self.job_id,
            "backup_definition_hash": self.ctx.get("definition_hash"),
            "transfer_mode": "pull_from_ssh" if job["source_via_ssh"] else "push_to_ssh",
            "source_path": job["source_path"],
            "remote_path": job["remote_path"],
            "snapshot": snapshot_name,
            "started_at": int(started),
            "finished_at": int(finished),
            "hard_link_incremental": job["link_dest"],
            "exclude": job["exclude"],
        }
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="rsync_boy_", suffix=".json", delete=False
        )
        try:
            json.dump(manifest, handle, indent=2)
            handle.write("\n")
        finally:
            handle.close()
        os.chmod(handle.name, 0o600)
        return handle.name

    def _prune_remote(self, transport, job):
        keep_days = job["remote_prune"]["keep_days"]
        if keep_days <= 0:
            return
        outcome = storage_operation({"action": "prune", "snapshot_root": job["remote_path"],
                                     "snapshot_prefix": job["snapshot_prefix"], "keep_days": keep_days}, transport)
        if outcome.get("prune_deferred"):
            self.log(f"[FILESYSTEM][{self.job_id}] Retention deferred while a restore drill holds the snapshot lock")

    def _prune_local(self, job):
        keep_days = job["remote_prune"]["keep_days"]
        if keep_days <= 0:
            return
        outcome = storage_operation({"action": "prune", "snapshot_root": job["remote_path"],
                                     "snapshot_prefix": job["snapshot_prefix"], "keep_days": keep_days})
        if outcome.get("prune_deferred"):
            self.log(f"[FILESYSTEM][{self.job_id}] Retention deferred while a restore drill holds the snapshot lock")
