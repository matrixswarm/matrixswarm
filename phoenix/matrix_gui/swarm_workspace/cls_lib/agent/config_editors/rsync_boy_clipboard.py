"""Validated, credential-free clipboard transfer for RsyncBoy jobs."""

from __future__ import annotations

import json
import re


CLIPBOARD_FORMAT = "matrixswarm.rsync_boy.jobs"
CLIPBOARD_VERSION = 1
MAX_CLIPBOARD_BYTES = 1024 * 1024
MAX_JOBS = 256

MYSQL_FACTORY = "mysql.mysqldump.MySQLDumpJob"
FILESYSTEM_FACTORY = "filesystem.rsync_snapshot.RsyncSnapshotJob"
SUPPORTED_FACTORIES = {MYSQL_FACTORY, FILESYSTEM_FACTORY}

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_PROFILE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class JobClipboardError(ValueError):
    """Clipboard text is not a safe RsyncBoy job bundle."""


def _string(mapping, key, default="", *, max_length=4096):
    value = mapping.get(key, default)
    if not isinstance(value, str):
        raise JobClipboardError(f"{key} must be text")
    value = value.strip()
    if len(value) > max_length:
        raise JobClipboardError(f"{key} is too long")
    return value


def _boolean(mapping, key, default):
    value = mapping.get(key, default)
    if not isinstance(value, bool):
        raise JobClipboardError(f"{key} must be true or false")
    return value


def _integer(mapping, key, default, minimum, maximum):
    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise JobClipboardError(f"{key} must be an integer")
    if not minimum <= value <= maximum:
        raise JobClipboardError(f"{key} must be between {minimum} and {maximum}")
    return value


def _absolute_non_root(path, field):
    if not path.startswith("/") or path == "/":
        raise JobClipboardError(f"{field} must be an absolute, non-root Linux path")
    return path


def _retention(config, maximum=3650):
    prune = config.get("remote_prune", {}) or {}
    if not isinstance(prune, dict):
        raise JobClipboardError("remote_prune must be an object")
    return {"keep_days": _integer(prune, "keep_days", 14, 0, maximum)}


def _normalize_mysql_config(config):
    remote_path = _absolute_non_root(
        _string(config, "remote_path", "/srv/backups/mysql/"), "remote_path"
    )
    local_tmp = _absolute_non_root(
        _string(config, "local_tmp", "/tmp/mysql_dumps"), "local_tmp"
    )
    prefix = _string(config, "filename_prefix", "", max_length=128)
    if prefix and not _SAFE_PREFIX.fullmatch(prefix):
        raise JobClipboardError("filename_prefix contains unsafe characters")
    return {
        "remote_path": remote_path,
        "local_tmp": local_tmp,
        "dump_flags": _string(config, "dump_flags", "--single-transaction"),
        "mysql_via_ssh": _boolean(config, "mysql_via_ssh", True),
        "compress": _boolean(config, "compress", True),
        "filename_prefix": prefix,
        "remote_prune": _retention(config),
    }


def _normalize_filesystem_config(config):
    prefix = _string(config, "snapshot_prefix", "sites", max_length=128)
    if not _SAFE_PREFIX.fullmatch(prefix):
        raise JobClipboardError("snapshot_prefix contains unsafe characters")
    excludes = config.get("exclude", [])
    if isinstance(excludes, str):
        excludes = [item.strip() for item in excludes.split(",") if item.strip()]
    if not isinstance(excludes, list) or len(excludes) > 256:
        raise JobClipboardError("exclude must be a list of at most 256 patterns")
    normalized_excludes = []
    for pattern in excludes:
        if not isinstance(pattern, str) or not pattern.strip() or len(pattern) > 512:
            raise JobClipboardError("exclude contains an invalid pattern")
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
        raise JobClipboardError("every job must be an object")
    job_id = _string(job, "id", max_length=128)
    if not _SAFE_ID.fullmatch(job_id):
        raise JobClipboardError("job id contains unsafe characters")
    factory = _string(job, "factory", max_length=128)
    if factory not in SUPPORTED_FACTORIES:
        raise JobClipboardError(f"unsupported factory for job '{job_id}'")
    schedule = job.get("schedule", {}) or {}
    config = job.get("config", {}) or {}
    if not isinstance(schedule, dict) or not isinstance(config, dict):
        raise JobClipboardError(f"invalid schedule or config for job '{job_id}'")
    normalized_config = (
        _normalize_filesystem_config(config)
        if factory == FILESYSTEM_FACTORY
        else _normalize_mysql_config(config)
    )
    ssh_profile = _string(job, "ssh_profile", "", max_length=128)
    if ssh_profile and not _SAFE_PROFILE_ID.fullmatch(ssh_profile):
        raise JobClipboardError("ssh_profile contains unsafe characters")
    normalized = {
        "id": job_id,
        "enabled": _boolean(job, "enabled", True),
        "factory": factory,
        "schedule": {
            "interval_sec": _integer(
                schedule, "interval_sec", 86400, 1, 31536000
            ),
            "run_on_boot": _boolean(schedule, "run_on_boot", False),
        },
        "config": normalized_config,
    }
    if ssh_profile:
        normalized["ssh_profile"] = ssh_profile
    return normalized


def normalize_jobs(jobs):
    if not isinstance(jobs, list) or len(jobs) > MAX_JOBS:
        raise JobClipboardError(f"jobs must be a list of at most {MAX_JOBS} items")
    normalized = [normalize_job(job) for job in jobs]
    ids = [job["id"] for job in normalized]
    if len(ids) != len(set(ids)):
        raise JobClipboardError("job ids must be unique")
    return normalized


def encode_jobs(jobs) -> str:
    document = {
        "format": CLIPBOARD_FORMAT,
        "version": CLIPBOARD_VERSION,
        "jobs": normalize_jobs(jobs),
    }
    return json.dumps(document, indent=2, ensure_ascii=False)


def decode_jobs(text) -> list:
    if not isinstance(text, str) or not text.strip():
        raise JobClipboardError("clipboard is empty")
    if len(text.encode("utf-8")) > MAX_CLIPBOARD_BYTES:
        raise JobClipboardError("clipboard job bundle is too large")
    try:
        document = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise JobClipboardError("clipboard does not contain valid JSON") from exc
    if not isinstance(document, dict):
        raise JobClipboardError("clipboard job bundle must be an object")
    if document.get("format") != CLIPBOARD_FORMAT:
        raise JobClipboardError("clipboard is not an RsyncBoy job bundle")
    if document.get("version") != CLIPBOARD_VERSION:
        raise JobClipboardError("unsupported RsyncBoy clipboard version")
    return normalize_jobs(document.get("jobs"))
