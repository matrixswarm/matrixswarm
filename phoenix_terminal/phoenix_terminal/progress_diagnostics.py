"""Validate self-reported work metadata; derive freshness and overdue work.

This independent public boundary deliberately does not import remote MatrixOS
code. Only fixed enums, bounded numbers and rebuilt service-path hints cross
into MCP.
"""
from datetime import datetime, timezone
import math
from pathlib import PurePosixPath
import re

OPERATIONS = {"llm_chat", "llm_embeddings", "llm_clusters", "log_read",
              "watch_setup", "event_listener", "quarantine", "site_checks", "traffic_read",
              "collector_read", "inbox_setup", "inbox_list", "inbox_read", "inbox_begin",
              "inbox_chunk", "inbox_commit", "inbox_cancel", "inbox_delete", "inbox_cleanup", "inbox_reply"}
REASONS = {"PERMISSION_DENIED", "MISSING_CONFIGURATION", "MISSING_PATH",
           "DEPENDENCY_UNAVAILABLE", "UPSTREAM_QUOTA_EXHAUSTED", "UPSTREAM_AUTH_FAILED",
           "RATE_LIMITED", "TIMEOUT", "RESOURCE_LIMIT", "IO_FAILURE", "OPERATION_FAILED",
           "INVALID_CONFIGURATION", "NO_WATCHES", "LISTENER_STOPPED"}
UNAVAILABLE = {"not_reported", "not_sampled", "unavailable", "missing", "unreadable", "invalid", "stale_process"}
PROGRESS_CODES = {"WORK_BLOCKED", "WORK_OVERDUE", "PROGRESS_EVIDENCE_STALE", "PROGRESS_EVIDENCE_UNAVAILABLE"}
TARGET_KINDS = {"watch_path", "access_log", "collector_log"}
TARGET_STATES = {"watching", "readable", "missing", "permission_denied", "invalid", "io_failure", "not_attempted", "disabled"}
PATH_ROOTS = ("/sites", "/var/log", "/var/www", "/srv/www")


def _path_hint(value):
    if not isinstance(value, str) or not re.fullmatch(r"/[A-Za-z0-9_./ -]{1,255}", value):
        return None
    parts = PurePosixPath(value).parts
    if ".." in parts or not any(value == root or value.startswith(root + "/") for root in PATH_ROOTS):
        return None
    if any(part.lower() in {".ssh", ".gnupg", ".env", "private", "secrets", "vaults", "keys", "certs"}
           or part.lower().startswith(".env.") for part in parts):
        return None
    if value.lower().endswith((".pem", ".key", ".p12", ".pfx")):
        return None
    return str(PurePosixPath(value))


def context_page(value, registered, published):
    if (not isinstance(value, dict) or value.get("state") != "available"
            or not isinstance(value.get("targets"), list) or len(value["targets"]) > 8):
        raise ValueError("Invalid target context")
    observed = _number(value.get("observed_at"), registered, published)
    total = _number(value.get("total_targets"), len(value["targets"]), 1000000, integer=True)
    if type(value.get("truncated")) is not bool or value["truncated"] != (total > len(value["targets"])):
        raise ValueError("Invalid target context coverage")
    rows = []
    for row in value["targets"]:
        if (not isinstance(row, dict) or not isinstance(row.get("kind"), str)
                or row["kind"] not in TARGET_KINDS or not isinstance(row.get("state"), str)
                or row["state"] not in TARGET_STATES
                or (row.get("reason") is not None and (not isinstance(row["reason"], str) or row["reason"] not in REASONS))):
            raise ValueError("Invalid target observation")
        rows.append(dict(kind=row["kind"], index=_number(row.get("index"), 1, 1000000, integer=True),
                         path=_path_hint(row.get("path")), state=row["state"], reason=row.get("reason")))
    return dict(state="available", observed_at=observed, observed_at_utc=timestamp(observed),
                total_targets=total, truncated=value["truncated"], targets=rows)


def _number(value, low, high, *, optional=False, integer=False):
    if value is None and optional:
        return None
    if (type(value) not in ((int,) if integer else (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError("Invalid progress number")
    return value


def progress_page(value, observed_at):
    if value is None:
        return {"state": "not_reported", "self_reported": True}
    try:
        if not isinstance(value, dict):
            raise ValueError("Invalid progress record")
        state = value.get("state")
        if isinstance(state, str) and state in UNAVAILABLE:
            return {"state": state, "self_reported": True}
        if state != "available":
            raise ValueError("Invalid progress state")
        now = datetime.fromisoformat(observed_at).timestamp()
        published = _number(value.get("published_at"), 1, min(now + 60, 4102444800))
        interval = _number(value.get("publish_interval_seconds"), 5, 3600)
        rows = value.get("operations")
        if not isinstance(rows, list) or not 1 <= len(rows) <= len(OPERATIONS):
            raise ValueError("Invalid progress operations")
        seen, projected = set(), []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid progress operation")
            name, reason, reported = row.get("name"), row.get("blocked_reason"), row.get("state")
            if (not isinstance(name, str) or name not in OPERATIONS or name in seen
                    or (reason is not None and (not isinstance(reason, str) or reason not in REASONS))
                    or reported not in {"idle", "working", "blocked"}):
                raise ValueError("Invalid progress enum")
            seen.add(name)
            item = dict(name=name, state=reported, blocked_reason=reason)
            item["registered_at"] = _number(row.get("registered_at"), 1, published)
            for key in ("last_attempt_at", "last_success_at", "last_failure_at", "active_since"):
                item[key] = _number(row.get(key), item["registered_at"], published, optional=True)
            item["expected_interval_seconds"] = _number(row.get("expected_interval_seconds"), 1, 86400, optional=True)
            item["timeout_seconds"] = _number(row.get("timeout_seconds"), 1, 3600)
            item["consecutive_failures"] = _number(row.get("consecutive_failures"), 0, 1000000, integer=True)
            item["active_count"] = _number(row.get("active_count"), 0, 64, integer=True)
            expected_state = "blocked" if reason else "working" if item["active_count"] else "idle"
            if (reported != expected_state or bool(item["active_count"]) != (item["active_since"] is not None)
                    or bool(reason) != bool(item["consecutive_failures"])
                    or (reason and item["last_failure_at"] is None)
                    or (item["active_count"] and item["last_attempt_at"] is None)
                    or (item["last_success_at"] is not None and item["last_attempt_at"] is None)):
                raise ValueError("Inconsistent progress record")
            overdue = bool(item["active_since"] is not None and now - item["active_since"] > item["timeout_seconds"])
            if item["expected_interval_seconds"] is not None:
                anchor = item["last_success_at"] or item["registered_at"]
                overdue |= now - anchor > item["expected_interval_seconds"] + item["timeout_seconds"]
            item.update(overdue=overdue, assessment="blocked" if reason else "overdue" if overdue else reported)
            item["timestamps_utc"] = {key: timestamp(item[key]) for key in
                                      ("last_attempt_at", "last_success_at", "last_failure_at", "active_since")}
            if "context" in row:
                item["context"] = context_page(row["context"], item["registered_at"], published)
            projected.append(item)
        fresh = now - published <= max(30, interval * 3)
        for item in projected:
            success, failure = item["last_success_at"], item["last_failure_at"]
            item["recovery"] = ("success_after_failure" if fresh and not item["blocked_reason"] and not item["overdue"]
                and failure is not None and success is not None and success > failure
                else "not_established" if failure is not None else "no_failure_reported")
        assessments = {row["assessment"] for row in projected}
        assessment = ("unverified" if not fresh else "blocked" if "blocked" in assessments else
                      "overdue" if "overdue" in assessments else "working" if "working" in assessments else "idle")
        return dict(state="available", self_reported=True, published_at=published,
                    publish_interval_seconds=interval, fresh=fresh, assessment=assessment, operations=projected,
                    application_health_verified=False)
    except (ValueError, TypeError, OverflowError):
        return {"state": "invalid", "self_reported": True}


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else ""


def progress_findings(progress):
    state = progress["state"]
    if state in {"not_sampled", "unavailable", "unreadable", "invalid", "stale_process"}:
        return [{"code": "PROGRESS_EVIDENCE_UNAVAILABLE", "timestamp": "", "evidence": state}]
    if state != "available":
        return []  # Older/uninstrumented agents have an explicit coverage limit.
    if not progress["fresh"]:
        return [{"code": "PROGRESS_EVIDENCE_STALE", "timestamp": timestamp(progress["published_at"]),
                 "evidence": "Progress publisher is overdue; current task state is unverified."}]
    findings = []
    for operation in progress["operations"]:
        if operation["blocked_reason"]:
            findings.append({"code": "WORK_BLOCKED", "operation": operation["name"],
                "timestamp": timestamp(operation["last_failure_at"]),
                "evidence": f"{operation['name']}: {operation['blocked_reason']}; consecutive_failures={operation['consecutive_failures']}; last_success={timestamp(operation['last_success_at']) or 'never reported'}"})
        if operation["overdue"]:
            findings.append({"code": "WORK_OVERDUE", "operation": operation["name"],
                "timestamp": timestamp(operation["active_since"] or operation["last_success_at"] or operation["registered_at"]),
                "evidence": f"{operation['name']}: exceeded its declared interval/timeout; functional progress is unverified."})
    return findings
