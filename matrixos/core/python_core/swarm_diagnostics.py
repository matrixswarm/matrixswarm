"""Read-only diagnostic snapshots. Never accept arbitrary file paths or decrypt logs.

Linux directory descriptors and O_NOFOLLOW prevent an agent-owned symlink from
turning the root reader into a reader of unrelated files. No source/config/env
content is returned. Heartbeat observations are not proof of application health.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import base64
import json
import math
import os
import re
import stat
import time

IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
BOOT = re.compile(r"[0-9_]{1,32}\Z")
MAX_AGENTS = 256
MAX_TAIL = 65536


def progress_snapshot(base, universe, boot, agent_id, matches):
    """Fixed runtime file only; never follow an agent-controlled link."""
    result = {"state": "unavailable"}
    if len(matches) != 1 or not isinstance(boot, str) or not BOOT.fullmatch(boot):
        return result
    try:
        with directory(base, "universes", "runtime", universe, boot, "comm", agent_id) as folder:
            fd = os.open("progress.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
            try:
                details = os.fstat(fd)
                if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1 or details.st_size > 16384:
                    raise ValueError("Invalid progress file")
                document = json.loads(os.read(fd, 16385))
            finally:
                os.close(fd)
        if (not isinstance(document, dict) or document.get("version") != 1
                or document.get("agent_id") != agent_id
                or type(document.get("pid")) is not int or document["pid"] != matches[0].get("pid")):
            return {"state": "stale_process"}
        started = matches[0].get("process_started_at")
        published = document.get("published_at")
        if (type(started) not in (int, float) or not math.isfinite(started)
                or type(published) not in (int, float) or not math.isfinite(published)
                or published < started):
            return {"state": "stale_process"}
        # Project only fixed metadata. Terminal validates types, bounds and enums
        # again; arbitrary strings/fields must never leave this root reader.
        from core.python_core.agent_progress import OPERATIONS, REASONS, target_context
        rows = document.get("operations")
        if not isinstance(rows, list) or not 1 <= len(rows) <= len(OPERATIONS):
            raise ValueError("Invalid progress operations")
        projected = []
        for row in rows:
            if (not isinstance(row, dict) or row.get("name") not in OPERATIONS
                    or row.get("state") not in {"idle", "working", "blocked"}
                    or row.get("blocked_reason") not in REASONS | {None}):
                raise ValueError("Invalid progress operation")
            item = {key: row[key] for key in ("name", "state", "blocked_reason")}
            for key in ("expected_interval_seconds", "timeout_seconds", "registered_at", "last_attempt_at", "last_success_at",
                        "last_failure_at", "consecutive_failures", "active_count", "active_since"):
                number = row.get(key)
                if number is not None and (type(number) not in (int, float) or not math.isfinite(number)):
                    raise ValueError("Invalid progress number")
                item[key] = number
            if "context" in row:
                item["context"] = target_context(row["context"])
            projected.append(item)
        interval = document.get("publish_interval_seconds")
        if type(interval) not in (int, float) or not math.isfinite(interval):
            raise ValueError("Invalid publication interval")
        return {"state": "available", "published_at": published,
                "publish_interval_seconds": interval, "operations": projected}
    except FileNotFoundError:
        return {"state": "missing"}
    except OSError:
        return {"state": "unreadable"}
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return {"state": "invalid"}


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("Invalid agent identity")
    return value


@contextmanager
def directory(base, *parts):
    """Traverse exact directories without following links, including ancestors."""
    if (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_PATH")
            or os.open not in os.supports_dir_fd):
        raise OSError("Safe diagnostic file reads require Linux")
    absolute = os.path.abspath(base)
    components = tuple(p for p in absolute.split("/") if p) + parts
    fd = os.open("/", (os.O_PATH if components else os.O_RDONLY) | os.O_DIRECTORY)
    try:
        for index, part in enumerate(components):
            # Fixed directory names include hello.moto; agent IDs remain stricter.
            if (not isinstance(part, str) or part in {".", ".."}
                    or not re.fullmatch(r"[A-Za-z0-9_.-]{1,255}", part)):
                raise ValueError("Invalid diagnostic directory component")
            # Shared ancestors intentionally allow traversal without listing.
            # O_PATH preserves that boundary. Only the final directory needs
            # read access for scandir; every component still rejects symlinks.
            access = os.O_RDONLY if index == len(components) - 1 else os.O_PATH
            child = os.open(part, access | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def thread_snapshot(base, universe, boot, agent_id, now, started=None):
    result = {"state": "unavailable", "records": [], "truncated": False, "rejected": 0, "heartbeat": "unknown"}
    if not isinstance(boot, str) or not BOOT.fullmatch(boot):
        return result
    try:
        with directory(base, "universes", "runtime", universe, boot, "comm", agent_id, "hello.moto") as fd:
            records = []
            with os.scandir(fd) as entries:
                for index, entry in enumerate(entries):
                    if index >= 256:
                        result["truncated"] = True
                        break
                    match = re.fullmatch(r"poke\.([A-Za-z0-9_-]{1,64})\.(\d{1,9})\.(\d{1,9})\.(\d{1,12})", entry.name)
                    if not match:
                        result["rejected"] += 1
                        continue
                    details = entry.stat(follow_symlinks=False)
                    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
                        result["rejected"] += 1
                        continue
                    name, timeout, sleep_for, wake_due = match.groups()
                    timeout, sleep_for, wake_due = int(timeout), int(sleep_for), int(wake_due)
                    seen = details.st_mtime
                    status = ("unknown" if seen > now + 60 or seen < 1 or wake_due > now + 86400
                              or (started is not None and seen < started) else
                              "sleeping" if wake_due > now else
                              "stale" if timeout and now - seen >= timeout else "alive")
                    records.append(dict(thread=name, status=status, last_seen=seen,
                        timeout=timeout, sleep_for=sleep_for, wake_due=wake_due))
            states = {r["status"] for r in records}
            result["heartbeat"] = ("stale" if "stale" in states else
                "unknown" if "unknown" in states or result["truncated"] or result["rejected"] else
                "recent" if "alive" in states else "sleeping" if states else "missing")
            records.sort(key=lambda r: (r["status"] != "stale", r["status"] != "unknown", r["thread"]))
            result.update(state="readable", records=records[:32], truncated=result["truncated"] or len(records) > 32)
    except FileNotFoundError:
        result.update(state="missing", heartbeat="missing")
    except OSError:
        result.update(state="unreadable", heartbeat="unreadable")
    return result


def heartbeat(base, universe, boot, agent_id, now):
    return thread_snapshot(base, universe, boot, agent_id, now)["heartbeat"]


def spawn_snapshot(base, universe, boot, agent_id, now):
    result = {"state": "unavailable", "count": 0, "recent_count": 0,
              "window_seconds": 60, "threshold": 3, "flip_tripping": None,
              "latest_spawns": [], "truncated": False, "rejected": 0}
    if not isinstance(boot, str) or not BOOT.fullmatch(boot):
        return result
    try:
        times = []
        with directory(base, "universes", "runtime", universe, boot, "comm", agent_id, "spawn") as fd:
            with os.scandir(fd) as entries:
                for index, entry in enumerate(entries):
                    if index >= 1024:
                        result["truncated"] = True
                        break
                    if not re.fullmatch(r"[0-9]{20}_[0-9a-fA-F-]{36}\.spawn", entry.name):
                        result["rejected"] += 1
                        continue
                    details = entry.stat(follow_symlinks=False)
                    if (not stat.S_ISREG(details.st_mode) or details.st_nlink != 1
                            or not 1 <= details.st_mtime <= now):
                        result["rejected"] += 1
                        continue
                    times.append(details.st_mtime)
        recent = sum(now - t <= 60 for t in times)
        result.update(state="readable", count=len(times), recent_count=recent,
            latest_spawns=sorted(times, reverse=True)[:5],
            flip_tripping=True if recent >= 3 else None if result["truncated"] or result["rejected"] else False)
    except FileNotFoundError:
        result["state"] = "missing"
    except OSError:
        result["state"] = "unreadable"
    return result


def process_health_snapshot(base, universe, boot, agent_id, matches, now):
    if len(matches) != 1:
        return {"state": "unavailable"}
    started = matches[0].get("process_started_at")
    if type(started) not in (int, float) or not math.isfinite(started) or not 1 <= started <= now + 60:
        started = None
    return {"state": "available", "process_started_at": started,
            "threads": thread_snapshot(base, universe, boot, agent_id, now, started),
            "spawns": spawn_snapshot(base, universe, boot, agent_id, now)}


def agents_snapshot(universe, infos, base="/matrix"):
    identifier(universe)
    now = time.time()
    grouped = {}
    for item in infos:
        if item.get("universe") != universe:
            continue
        uid = identifier(item.get("universal_id"))
        grouped.setdefault(uid, []).append(item)
    rows = []
    progress_budget = 96 * 1024
    process_budget = 64 * 1024
    for uid in sorted(grouped)[:MAX_AGENTS]:
        matches = grouped[uid]
        boot = matches[0].get("reboot_uuid")
        health = process_health_snapshot(base, universe, boot, uid, matches, now)
        pulse = health.get("threads", {}).get("heartbeat", "unknown")
        size = len(json.dumps(health, separators=(",", ":")).encode("utf-8"))
        if size > process_budget:
            health = {"state": "not_sampled"}
        else:
            process_budget -= size
        progress = progress_snapshot(base, universe, boot, uid, matches)
        size = len(json.dumps(progress, separators=(",", ":")).encode("utf-8"))
        if size > progress_budget:
            progress = {"state": "not_sampled"}
        else:
            progress_budget -= size
        rows.append({"agent_id": uid, "process_count": len(matches),
                     "boot_id": boot if isinstance(boot, str) and BOOT.fullmatch(boot) else None,
                     "heartbeat": pulse, "process_health": health,
                     "progress": progress})
    return {"version": 1, "universe": universe,
            "observed_at": datetime.fromtimestamp(now, timezone.utc).isoformat(), "agents": rows,
            "truncated": len(grouped) > MAX_AGENTS}


def log_snapshot(universe, agent_id, infos, base="/matrix", *, max_bytes=MAX_TAIL, include_progress=True):
    identifier(universe)
    identifier(agent_id)
    if type(max_bytes) is not int or not 1024 <= max_bytes <= MAX_TAIL:
        raise ValueError("Invalid log byte limit")
    # Only the current observed boot, never an old archive chosen by a caller.
    boots = {i.get("reboot_uuid") for i in infos if i.get("universe") == universe}
    boot = next(iter(boots)) if len(boots) == 1 else None
    now = time.time()
    result = {"version": 1, "universe": universe, "agent_id": agent_id,
              "observed_at": datetime.fromtimestamp(now, timezone.utc).isoformat(), "boot_id": boot,
              "state": "boot_unavailable", "tail": "", "truncated": False}
    if include_progress:
        matches = [i for i in infos if i.get("universe") == universe and i.get("universal_id") == agent_id]
        result["progress"] = progress_snapshot(base, universe, boot, agent_id, matches)
        result["process_health"] = process_health_snapshot(base, universe, boot, agent_id, matches, now)
    if not isinstance(boot, str) or not BOOT.fullmatch(boot):
        result["boot_id"] = None
        return result
    try:
        with directory(base, "universes", "static", universe, boot, "comm", agent_id, "logs") as folder:
            fd = os.open("agent.log", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
            try:
                details = os.fstat(fd)
                if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
                    raise OSError("Not a private regular log file")
                start = max(0, details.st_size - max_bytes)
                os.lseek(fd, start, os.SEEK_SET)
                raw = os.read(fd, max_bytes)
                if start:
                    raw = raw.partition(b"\n")[2]  # Drop partial first record.
                raw = raw.rpartition(b"\n")[0] if raw else b""  # Drop in-flight last record.
                result.update(state="readable", tail=base64.b64encode(raw).decode("ascii"),
                              truncated=start > 0)
            finally:
                os.close(fd)
    except FileNotFoundError:
        result["state"] = "missing"
    except OSError:
        result["state"] = "unreadable"
    return result
