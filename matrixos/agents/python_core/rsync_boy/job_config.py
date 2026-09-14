"""Strict, credential-free schema for RsyncBoy's remotely managed jobs."""

from __future__ import annotations

import re


MYSQL_FACTORY = "mysql.mysqldump.MySQLDumpJob"
FILESYSTEM_FACTORY = "filesystem.rsync_snapshot.RsyncSnapshotJob"
SUPPORTED_FACTORIES = {MYSQL_FACTORY, FILESYSTEM_FACTORY}
MAX_JOBS = 256

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _string(mapping, key, default="", *, max_length=4096):
    value = mapping.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    value = value.strip()
    if len(value) > max_length:
        raise ValueError(f"{key} is too long")
    return value


def _boolean(mapping, key, default):
    value = mapping.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


def _integer(mapping, key, default, minimum, maximum):
    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def _absolute_non_root(path, field):
    if not path.startswith("/") or path == "/":
        raise ValueError(f"{field} must be an absolute, non-root Linux path")
    return path


def _retention(config, maximum=3650):
    prune = config.get("remote_prune", {}) or {}
    if not isinstance(prune, dict):
        raise ValueError("remote_prune must be an object")
    return {"keep_days": _integer(prune, "keep_days", 14, 0, maximum)}


def _normalize_mysql(config):
    prefix = _string(config, "filename_prefix", "", max_length=128)
    if prefix and not _SAFE_PREFIX.fullmatch(prefix):
        raise ValueError("filename_prefix contains unsafe characters")
    return {
        "remote_path": _absolute_non_root(
            _string(config, "remote_path", "/srv/backups/mysql/"), "remote_path"
        ),
        "local_tmp": _absolute_non_root(
            _string(config, "local_tmp", "/tmp/mysql_dumps"), "local_tmp"
        ),
        "dump_flags": _string(config, "dump_flags", "--single-transaction"),
        "mysql_via_ssh": _boolean(config, "mysql_via_ssh", True),
        "compress": _boolean(config, "compress", True),
        "filename_prefix": prefix,
        "remote_prune": _retention(config),
    }


def _normalize_filesystem(config):
    prefix = _string(config, "snapshot_prefix", "sites", max_length=128)
    if not _SAFE_PREFIX.fullmatch(prefix):
        raise ValueError("snapshot_prefix contains unsafe characters")
    excludes = config.get("exclude", [])
    if isinstance(excludes, str):
        excludes = [part.strip() for part in excludes.split(",") if part.strip()]
    if not isinstance(excludes, list) or len(excludes) > 256:
        raise ValueError("exclude must be a list of at most 256 patterns")
    normalized_excludes = []
    for pattern in excludes:
        if not isinstance(pattern, str) or not pattern.strip() or len(pattern) > 512:
            raise ValueError("exclude contains an invalid pattern")
        normalized_excludes.append(pattern.strip())
    return {
        "source_via_ssh": _boolean(config, "source_via_ssh", True),
        "source_path": _absolute_non_root(
            _string(config, "source_path", "/sites"), "source_path"
        ),
        "remote_path": _absolute_non_root(
            _string(config, "remote_path", "/backup/snapshots/sites"),
            "remote_path",
        ),
        "snapshot_prefix": prefix,
        "exclude": normalized_excludes,
        "link_dest": _boolean(config, "link_dest", True),
        "preserve_hard_links": _boolean(config, "preserve_hard_links", True),
        "preserve_acls": _boolean(config, "preserve_acls", True),
        "preserve_xattrs": _boolean(config, "preserve_xattrs", True),
        "remote_prune": _retention(config),
    }


def normalize_job(job):
    if not isinstance(job, dict):
        raise ValueError("every job must be an object")
    job_id = _string(job, "id", max_length=128)
    if not _SAFE_ID.fullmatch(job_id):
        raise ValueError("job id contains unsafe characters")
    factory = _string(job, "factory", max_length=128)
    if factory not in SUPPORTED_FACTORIES:
        raise ValueError(f"unsupported factory for job '{job_id}'")
    schedule = job.get("schedule", {}) or {}
    config = job.get("config", {}) or {}
    if not isinstance(schedule, dict) or not isinstance(config, dict):
        raise ValueError(f"invalid schedule or config for job '{job_id}'")
    if "ssh" in config or "mysql" in config:
        raise ValueError("job definitions cannot contain credentials")
    return {
        "id": job_id,
        "enabled": _boolean(job, "enabled", True),
        "factory": factory,
        "schedule": {
            "interval_sec": _integer(
                schedule, "interval_sec", 86400, 1, 31536000
            ),
            "run_on_boot": _boolean(schedule, "run_on_boot", False),
        },
        "config": (
            _normalize_filesystem(config)
            if factory == FILESYSTEM_FACTORY
            else _normalize_mysql(config)
        ),
    }


def normalize_jobs(jobs):
    if not isinstance(jobs, list) or len(jobs) > MAX_JOBS:
        raise ValueError(f"jobs must be a list of at most {MAX_JOBS} items")
    normalized = [normalize_job(job) for job in jobs]
    ids = [job["id"] for job in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError("job ids must be unique")
    return normalized


def normalize_poll_interval(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 86400:
        raise ValueError("poll_interval must be an integer between 1 and 86400")
    return value
