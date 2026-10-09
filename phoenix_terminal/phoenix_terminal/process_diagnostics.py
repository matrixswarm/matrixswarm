"""Bounded thread/spawn metadata, independently projected at the MCP boundary.

These are observations of agent-writable files, not an attestation of health.
Derive statuses from numeric evidence; never accept caller-supplied conclusions.
"""
from datetime import datetime
import math
import re

from .progress_diagnostics import timestamp

THREAD = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
PROCESS_CODES = {"THREAD_HEARTBEAT_STALE", "SPAWN_BURST", "PROCESS_HEALTH_INCOMPLETE"}
UNAVAILABLE = {"not_reported", "not_sampled", "unavailable", "invalid"}
FILE_STATES = {"readable", "missing", "unreadable", "unavailable"}


def _number(value, low, high, *, integer=False):
    if (type(value) not in ((int,) if integer else (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError("Invalid process metadata number")
    return value


def _section(value):
    if not isinstance(value, dict) or value.get("state") not in FILE_STATES:
        raise ValueError("Invalid process metadata state")
    if type(value.get("truncated")) is not bool:
        raise ValueError("Invalid process metadata coverage")
    return dict(state=value["state"], truncated=value["truncated"],
                rejected=_number(value.get("rejected"), 0, 1024, integer=True))


def process_page(value, observed_at):
    if value is None:
        return {"state": "not_reported", "complete": False}
    try:
        if not isinstance(value, dict):
            raise ValueError("Invalid process metadata")
        state = value.get("state")
        if isinstance(state, str) and state in UNAVAILABLE:
            return {"state": state, "complete": False}
        if state != "available":
            raise ValueError("Invalid process metadata state")
        now = datetime.fromisoformat(observed_at).timestamp()
        started = value.get("process_started_at")
        if started is not None:
            started = _number(started, 1, min(now + 60, 4102444800))
        source = value.get("threads")
        threads = _section(source)
        records = source.get("records")
        if not isinstance(records, list) or len(records) > 32:
            raise ValueError("Invalid thread list")
        projected = []
        for row in records:
            if not isinstance(row, dict) or not isinstance(row.get("thread"), str) or not THREAD.fullmatch(row["thread"]):
                raise ValueError("Invalid thread identity")
            seen = _number(row.get("last_seen"), 0, 4102444800)
            timeout = _number(row.get("timeout"), 0, 999999999, integer=True)
            sleep_for = _number(row.get("sleep_for"), 0, 999999999, integer=True)
            wake_due = _number(row.get("wake_due"), 0, 999999999999, integer=True)
            status = ("unknown" if started is None or seen < started or seen > now + 60
                      or seen < 1 or wake_due > now + 86400 else
                      "sleeping" if wake_due > now else
                      "stale" if timeout and now - seen >= timeout else "alive")
            projected.append(dict(thread=row["thread"], status=status, last_seen=seen,
                last_seen_utc=timestamp(seen), age_seconds=round(max(0, now - seen), 3),
                timeout=timeout, sleep_for=sleep_for, wake_due=wake_due,
                wake_due_utc=timestamp(wake_due) if 0 < wake_due <= 4102444800 else ""))
        if threads["state"] != "readable" and projected:
            raise ValueError("Thread evidence contradicts coverage")
        states = {r["status"] for r in projected}
        threads.update(records=projected, complete=bool(projected) and threads["state"] == "readable"
                       and not threads["truncated"] and not threads["rejected"] and "unknown" not in states)
        source = value.get("spawns")
        spawns = _section(source)
        count = _number(source.get("count"), 0, 1024, integer=True)
        recent = _number(source.get("recent_count"), 0, count, integer=True)
        latest = source.get("latest_spawns")
        if not isinstance(latest, list) or len(latest) != min(count, 5):
            raise ValueError("Invalid spawn evidence")
        latest = [_number(t, 1, min(now, 4102444800)) for t in latest]
        if latest != sorted(latest, reverse=True):
            raise ValueError("Unordered spawn evidence")
        recent_in_sample = sum(now - t <= 60 for t in latest)
        if recent < recent_in_sample or (recent_in_sample < len(latest) and recent != recent_in_sample):
            raise ValueError("Inconsistent spawn window")
        if spawns["state"] != "readable" and count:
            raise ValueError("Spawn evidence contradicts coverage")
        complete = spawns["state"] == "readable" and not spawns["truncated"] and not spawns["rejected"]
        # Three recent timestamps suffice even when the directory scan was capped.
        burst = True if recent_in_sample >= 3 else False if complete else None
        spawns.update(count=count, recent_count=recent, latest_spawns=latest,
            latest_spawns_utc=[timestamp(t) for t in latest], complete=complete,
            window_seconds=60, threshold=3, flip_tripping=burst,
            time_basis="file_mtime", count_includes_initial_spawn=True)
        assessment = ("attention_required" if "stale" in states or burst else
                      "incomplete" if not threads["complete"] or not complete else "observed")
        return dict(state="available", process_started_at=started, threads=threads, spawns=spawns,
            assessment=assessment, complete=threads["complete"] and complete,
            expected_threads_verified=False, application_health_verified=False)
    except (ValueError, TypeError, OverflowError, OSError):
        return {"state": "invalid", "complete": False}


def process_findings(health):
    if health["state"] == "not_reported":
        return []
    findings = []
    if health["state"] == "available":
        for row in health["threads"]["records"]:
            if row["status"] == "stale":
                findings.append(dict(code="THREAD_HEARTBEAT_STALE", thread=row["thread"],
                    timestamp=row["last_seen_utc"],
                    evidence=f"{row['thread']}: heartbeat age={row['age_seconds']}s exceeds timeout={row['timeout']}s; process presence does not establish worker progress."))
        spawns = health["spawns"]
        if spawns["flip_tripping"] is True:
            findings.append(dict(code="SPAWN_BURST", timestamp=spawns["latest_spawns_utc"][0],
                evidence=f"{spawns['recent_count']} observed spawn records within 60 seconds (threshold 3; initial spawn included). Restart causes and recovery are unverified."))
    if not health["complete"]:
        findings.append(dict(code="PROCESS_HEALTH_INCOMPLETE", timestamp="",
            evidence="Thread/spawn coverage incomplete; missing, stale-process, rejected, unreadable or capped metadata cannot establish healthy workers."))
    return findings
