"""Local backup-storage accounting for RsyncBoy jobs.

The scanner reports allocated bytes, does not follow symbolic links, and
deduplicates hard-linked files by device/inode.  That makes its totals match
the physical cost of incremental snapshot trees instead of summing every
logical snapshot copy.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time

try:
    from rsync_boy.job_config import FILESYSTEM_FACTORY, MYSQL_FACTORY, RESTORE_FACTORY
except ImportError:  # Direct module loading used by focused unit tests.
    from job_config import FILESYSTEM_FACTORY, MYSQL_FACTORY, RESTORE_FACTORY


MAX_SCAN_ENTRIES = 5_000_000
MAX_SCAN_SECONDS = 120
MAX_DU_SECONDS = 900


class StorageScanLimit(RuntimeError):
    """Raised when an unexpectedly large tree exceeds the safety bound."""


def _allocated_bytes(stat_result) -> int:
    blocks = getattr(stat_result, "st_blocks", None)
    if isinstance(blocks, int):
        return max(0, blocks * 512)
    return max(0, int(stat_result.st_size))


def _inode_key(stat_result, path: str):
    device = getattr(stat_result, "st_dev", 0)
    inode = getattr(stat_result, "st_ino", 0)
    if inode:
        return device, inode
    return "path", os.path.abspath(path)


def _storage_spec(job: dict):
    config = job.get("config", {}) or {}
    factory = job.get("factory")
    if factory == FILESYSTEM_FACTORY:
        if not config.get("source_via_ssh"):
            return None
        return {
            "root": str(config.get("remote_path") or ""),
            "kind": "tree",
        }
    if factory == MYSQL_FACTORY:
        prefix = str(config.get("filename_prefix") or "")
        return {
            "root": str(config.get("local_tmp") or ""),
            "kind": "mysql",
            "pattern": re.compile(
                rf"^{re.escape(prefix)}_\d{{8}}_\d{{6}}"
                r"\.sql(?:\.gz)?(?:\.manifest\.json)?$"
            ),
        }
    return None


def _measure_tree(
    spec: dict,
    entry_budget: list[int],
    deadline: float,
):
    root = spec["root"]
    if not root or not os.path.lexists(root):
        return 0, "missing", False
    if os.path.islink(root):
        raise OSError("backup root is a symbolic link")

    if spec["kind"] == "tree" and shutil.which("du"):
        try:
            result = subprocess.run(
                ["du", "-s", "-B1", "--", root],
                capture_output=True,
                text=True,
                timeout=MAX_DU_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise StorageScanLimit(
                f"native disk-usage scan exceeded {MAX_DU_SECONDS} seconds"
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or "native disk-usage scan failed").strip()
            raise OSError(detail[:500])
        try:
            allocated = int((result.stdout or "").split(None, 1)[0])
        except (IndexError, ValueError) as exc:
            raise OSError("native disk-usage scan returned invalid output") from exc
        return max(0, allocated), "ready", False

    local_sizes = {}
    partial = False
    stack = [root]
    mysql_pattern = spec.get("pattern")

    while stack:
        if time.monotonic() >= deadline:
            raise StorageScanLimit(
                f"storage scan exceeded {MAX_SCAN_SECONDS} seconds"
            )
        current = stack.pop()
        try:
            if current == root and mysql_pattern is not None:
                with os.scandir(current) as entries:
                    children = [
                        entry.path
                        for entry in entries
                        if mysql_pattern.fullmatch(entry.name)
                        and entry.is_file(follow_symlinks=False)
                    ]
                stack.extend(children)
                continue

            stat_result = os.stat(current, follow_symlinks=False)
            entry_budget[0] += 1
            if entry_budget[0] > MAX_SCAN_ENTRIES:
                raise StorageScanLimit(
                    f"storage scan exceeded {MAX_SCAN_ENTRIES:,} entries"
                )

            key = _inode_key(stat_result, current)
            size = _allocated_bytes(stat_result)
            local_sizes.setdefault(key, size)

            if os.path.isdir(current) and not os.path.islink(current):
                try:
                    with os.scandir(current) as entries:
                        stack.extend(entry.path for entry in entries)
                except OSError:
                    partial = True
        except FileNotFoundError:
            # A retention pass can remove an old snapshot while this read-only
            # scan is running.  The next cached refresh will reconcile it.
            partial = True
        except PermissionError:
            partial = True

    return sum(local_sizes.values()), "partial" if partial else "ready", partial


def _path_is_within(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath((path, parent)) == parent
    except ValueError:
        return False


def _configured_total(contributions: list[tuple[dict, int]]) -> int:
    """Deduplicate identical/nested configured roots in the global total."""
    tree_roots = []
    for spec, size in contributions:
        if spec["kind"] != "tree":
            continue
        root = os.path.abspath(spec["root"])
        if any(root == existing[0] or _path_is_within(root, existing[0])
               for existing in tree_roots):
            continue
        tree_roots = [
            existing for existing in tree_roots
            if not _path_is_within(existing[0], root)
        ]
        tree_roots.append((root, size))

    total = sum(size for _root, size in tree_roots)
    mysql_roots = set()
    for spec, size in contributions:
        if spec["kind"] != "mysql":
            continue
        root = os.path.abspath(spec["root"])
        key = (root, spec["pattern"].pattern)
        if key in mysql_roots:
            continue
        mysql_roots.add(key)
        if any(root == tree_root or _path_is_within(root, tree_root)
               for tree_root, _size in tree_roots):
            continue
        total += size
    return total


def measure_backup_storage(jobs: list[dict], progress=None) -> dict:
    """Return per-job and unique total allocated bytes for local backups."""
    entry_budget = [0]
    results = {}
    contributions = []
    partial = False
    completed_jobs = 0
    deadline = time.monotonic() + MAX_SCAN_SECONDS

    for job in jobs:
        job_id = str(job.get("id") or "")
        spec = _storage_spec(job)
        if job.get("factory") == RESTORE_FACTORY:
            results[job_id] = {"bytes": None, "state": "scratch",
                               "detail": "Temporary restore copy; excluded from backup storage totals"}
        elif spec is None:
            results[job_id] = {
                "bytes": None,
                "state": "remote",
                "detail": "Backup data is stored on the selected SSH server",
            }
        else:
            try:
                job_bytes, state, job_partial = _measure_tree(
                    spec, entry_budget, deadline
                )
                results[job_id] = {
                    "bytes": job_bytes,
                    "state": state,
                    "detail": spec["root"],
                }
                contributions.append((spec, job_bytes))
                partial = partial or job_partial
            except (OSError, StorageScanLimit) as exc:
                results[job_id] = {
                    "bytes": None,
                    "state": "error",
                    "detail": str(exc),
                }
                partial = True

        completed_jobs += 1
        if progress is not None:
            progress(
                job_id,
                dict(results[job_id]),
                _configured_total(contributions),
                partial,
                completed_jobs,
                len(jobs),
            )

    return {
        "total_bytes": _configured_total(contributions),
        "partial": partial,
        "jobs": results,
        "completed_jobs": completed_jobs,
        "job_count": len(jobs),
    }
