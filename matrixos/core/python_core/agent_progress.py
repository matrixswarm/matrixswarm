"""Small self-reported work records with bounded service-path context.

Heartbeat emission must never mark an operation successful. Only the code that
actually completes the measured operation calls success (or exits attempt()).
"""
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import threading
import time

OPERATIONS = {"llm_chat", "llm_embeddings", "llm_clusters", "log_read",
              "watch_setup", "event_listener", "quarantine", "site_checks", "traffic_read",
              "collector_read", "inbox_setup", "inbox_list", "inbox_read", "inbox_begin",
              "inbox_chunk", "inbox_commit", "inbox_cancel", "inbox_delete", "inbox_cleanup", "inbox_reply"}
REASONS = {"PERMISSION_DENIED", "MISSING_CONFIGURATION", "MISSING_PATH",
           "DEPENDENCY_UNAVAILABLE", "UPSTREAM_QUOTA_EXHAUSTED", "UPSTREAM_AUTH_FAILED",
           "RATE_LIMITED", "TIMEOUT", "RESOURCE_LIMIT", "IO_FAILURE", "OPERATION_FAILED",
           "INVALID_CONFIGURATION", "NO_WATCHES", "LISTENER_STOPPED"}
TARGET_KINDS = {"watch_path", "access_log", "collector_log"}
TARGET_STATES = {"watching", "readable", "missing", "permission_denied", "invalid", "io_failure", "not_attempted", "disabled"}
PATH_ROOTS = ("/sites", "/var/log", "/var/www", "/srv/www")
MAX_RECORD_BYTES = 16384


def path_hint(value):
    """Service-path labels only; no arbitrary path or config is disclosed."""
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


def path_target(kind, index, path, state, reason=None):
    if (kind not in TARGET_KINDS or type(index) is not int or not 1 <= index <= 1000000
            or state not in TARGET_STATES or reason not in REASONS | {None}):
        raise ValueError("Invalid diagnostic target")
    return dict(kind=kind, index=index, path=path_hint(path), state=state, reason=reason)


def target_context(value):
    """Rebuild a bounded context when reading an agent-writable file."""
    if not isinstance(value, dict) or value.get("state") != "available":
        raise ValueError("Invalid target context")
    observed, total = value.get("observed_at"), value.get("total_targets")
    rows = value.get("targets")
    if (type(observed) not in (int, float) or not 1 <= observed <= 4102444800
            or type(total) is not int or not 0 <= total <= 1000000
            or not isinstance(rows, list) or len(rows) > 8 or total < len(rows)
            or type(value.get("truncated")) is not bool or value["truncated"] != (total > len(rows))):
        raise ValueError("Invalid target context bounds")
    projected = [path_target(row["kind"], row["index"], row.get("path"), row["state"], row.get("reason"))
                 for row in rows]
    return dict(state="available", observed_at=observed, total_targets=total,
                truncated=value["truncated"], targets=projected)


def failure_reason(exc):
    """Map locally; exception messages are never written to the progress file."""
    reported = getattr(exc, "reason", None)
    if isinstance(reported, str) and reported in REASONS:
        return reported
    if isinstance(exc, PermissionError) or getattr(exc, "errno", None) in (errno.EACCES, errno.EPERM):
        return "PERMISSION_DENIED"
    if isinstance(exc, FileNotFoundError) or getattr(exc, "errno", None) == errno.ENOENT:
        return "MISSING_PATH"
    if isinstance(exc, ImportError):
        return "DEPENDENCY_UNAVAILABLE"
    if isinstance(exc, TimeoutError) or type(exc).__name__ == "APITimeoutError":
        return "TIMEOUT"
    # OpenAI SDK error body/code shape, not arbitrary message substring matches.
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    code = error.get("code") if isinstance(error, dict) else None
    kind = error.get("type") if isinstance(error, dict) else None
    if code in ("insufficient_quota", "credit_balance_exhausted") or kind == "insufficient_quota":
        return "UPSTREAM_QUOTA_EXHAUSTED"
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return "UPSTREAM_AUTH_FAILED"
    if status == 429:
        return "RATE_LIMITED"
    if getattr(exc, "errno", None) in (errno.ENOSPC, errno.EMFILE, errno.ENFILE):
        return "RESOURCE_LIMIT"
    return "IO_FAILURE" if isinstance(exc, OSError) else "OPERATION_FAILED"


class AgentProgress:
    """Atomic metadata, rate limited except for state/context transitions.

    Publication failures never break agent work; a missing/stale record is an
    explicit diagnostic coverage gap. An idle operation retains its last error
    until that same operation succeeds. Concurrent completions are serialized.
    """
    def __init__(self, agent, operations, *, publish_interval=5):
        self._folder = Path(agent.path_resolution["comm_path_resolved"])
        self._agent_id = agent.command_line_args["universal_id"]
        self._lock = threading.RLock()
        self._last_flush = float("-inf")
        self._publish_interval = max(5, min(3600, float(publish_interval)))
        self._operations = {}
        self._active = {}
        self._sequence = 0
        for name, (interval, timeout) in operations.items():
            if name not in OPERATIONS or (interval is not None and not 1 <= interval <= 86400) or not 1 <= timeout <= 3600:
                raise ValueError("Invalid progress operation contract")
            self._operations[name] = dict(name=name, expected_interval_seconds=interval,
                timeout_seconds=timeout, registered_at=time.time(), last_attempt_at=None, last_success_at=None,
                last_failure_at=None, consecutive_failures=0, blocked_reason=None)
            self._active[name] = {}
        self.flush(force=True)

    def begin(self, name):
        with self._lock:
            row = self._operations[name]
            now = time.time()
            row["last_attempt_at"] = now
            if len(self._active[name]) >= 64:
                self.block(name, "RESOURCE_LIMIT")
                return None
            self._sequence += 1
            token = self._sequence
            self._active[name][token] = now
            self.flush()
            return token

    def finish(self, name, token, reason=None, *, clear_failure=True):
        with self._lock:
            if token is None or token not in self._active[name]:
                return
            started = self._active[name].pop(token)
            if reason is not None:
                self.block(name, reason)
            else:
                row = self._operations[name]
                was_blocked = bool(row["blocked_reason"])
                row["last_success_at"] = time.time()
                # A late completion from an older concurrent attempt cannot
                # erase a failure that happened after that attempt started.
                if clear_failure and (row["last_failure_at"] is None or started >= row["last_failure_at"]):
                    row.update(consecutive_failures=0, blocked_reason=None)
                self.flush(force=was_blocked and not row["blocked_reason"])

    def set_context(self, name, targets):
        """Publish observations from actual agent work, not extra probes."""
        with self._lock:
            failed = {"missing", "permission_denied", "invalid", "io_failure"}
            ordered = sorted(targets, key=lambda row: row["state"] not in failed)
            context = target_context(dict(state="available", observed_at=time.time(),
                total_targets=len(ordered), truncated=len(ordered) > 8, targets=ordered[:8]))
            # Context has a shared per-agent budget, including repeated ops.
            used = sum(len(row.get("context", {}).get("targets", []))
                       for key, row in self._operations.items() if key != name)
            context["targets"] = context["targets"][:max(0, 16 - used)]
            context["truncated"] = context["total_targets"] > len(context["targets"])
            previous = self._operations[name].get("context", {})
            changed = any(previous.get(key) != context[key] for key in ("targets", "total_targets", "truncated"))
            self._operations[name]["context"] = context
            self.flush(force=changed)

    def block(self, name, reason):
        if reason not in REASONS:
            raise ValueError("Invalid progress failure reason")
        with self._lock:
            row = self._operations[name]
            changed = row["blocked_reason"] != reason
            row.update(blocked_reason=reason, last_failure_at=time.time(),
                       consecutive_failures=min(1000000, row["consecutive_failures"] + 1))
            self.flush(force=changed)

    def abandon(self, name, token):
        """A rejected/no-op request proves neither success nor agent failure."""
        with self._lock:
            self._active[name].pop(token, None)
            self.flush()

    @contextmanager
    def attempt(self, name):
        token = self.begin(name)
        try:
            yield
        except BaseException as exc:
            self.finish(name, token, failure_reason(exc))
            raise
        else:
            self.finish(name, token)

    def flush(self, *, force=False):
        with self._lock:
            now = time.monotonic()
            if not force and now - self._last_flush < 5:
                return
            temporary = None
            try:
                rows = []
                for name, row in self._operations.items():
                    active = self._active[name]
                    rows.append(dict(row, active_count=len(active),
                        active_since=min(active.values()) if active else None,
                        state="blocked" if row["blocked_reason"] else "working" if active else "idle"))
                document = dict(version=1, agent_id=self._agent_id, pid=os.getpid(),
                    published_at=time.time(), publish_interval_seconds=self._publish_interval,
                    operations=rows)
                encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
                # Keep the file inside the reader's bound even when many
                # operations report long labels. Trim only exported context;
                # preserve failure records and count every omitted target.
                while len(encoded) > MAX_RECORD_BYTES:
                    row = next((item for item in reversed(rows) if item.get("context", {}).get("targets")), None)
                    if row is None:
                        return  # A coverage gap is safer than an oversized file.
                    context = dict(row["context"], targets=row["context"]["targets"][:-1], truncated=True)
                    row["context"] = context
                    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
                fd, temporary = tempfile.mkstemp(prefix=".progress-", dir=self._folder)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(encoded)
                os.replace(temporary, self._folder / "progress.json")
                temporary = None
            except OSError:
                pass
            finally:
                self._last_flush = now
                if temporary is not None:
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass
