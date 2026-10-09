"""Fail-closed Terminal connection lifecycle and scoped alert reads."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import re
import secrets
import threading
import time
from typing import Callable, Mapping

from .alert_access import AlertReadError, public_alert_page
from .connection_approval import (
    ApprovalResource,
    CURRENT_OPERATIONS,
    ConnectionApprovalRequest,
    PendingApprovalQueue,
)


MAX_CONNECTION_RECORDS = 32
_BASE_CLIENT_METHODS = frozenset(
    {"terminal.status", "connection.request", "connection.status", "connection.disconnect"}
)


def _exact_params(params, names):
    if not isinstance(params, dict) or set(params) != set(names):
        expected = ", ".join(sorted(names)) or "no parameters"
        raise ValueError(f"Request requires exactly: {expected}")


def _plain(value, label, minimum=1, maximum=160):
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} has an invalid length")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{label} contains unsafe text")
    return value


def _secret_digest(secret):
    _plain(secret, "Client secret", minimum=32, maximum=256)
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TerminalSnapshot:
    vault_label: str
    vault_revision: str
    resources: tuple[ApprovalResource, ...]
    approval_lifetime_seconds: int

    def __post_init__(self):
        # Reuse the approval contract to validate every display/resource field.
        ConnectionApprovalRequest(
            request_id="snapshot-validation",
            client_label="snapshot-validation",
            vault_label=self.vault_label,
            vault_revision=self.vault_revision,
            resources=self.resources,
            operations=tuple(sorted({op for item in self.resources for op in item.operations})),
            lifetime_seconds=self.approval_lifetime_seconds,
        )


@dataclass
class _ConnectionRecord:
    request: ConnectionApprovalRequest
    secret_digest: str
    state: str = "pending"
    reason: str = "Awaiting operator decision"
    deadline: float | None = None


class TerminalConnectionBroker:
    """Own requests and grants; the client API deliberately has no approve method."""

    def __init__(
        self,
        snapshot: TerminalSnapshot,
        *,
        clock: Callable[[], float] = time.monotonic,
        queue: PendingApprovalQueue | None = None,
        operation_handlers: Mapping[str, Callable[..., dict]] | None = None,
    ):
        if not isinstance(snapshot, TerminalSnapshot):
            raise TypeError("snapshot must be a TerminalSnapshot")
        self.snapshot = snapshot
        self._clock = clock
        self._queue = queue or PendingApprovalQueue()
        self._records: OrderedDict[str, _ConnectionRecord] = OrderedDict()
        self._closed = False
        self._lock = threading.RLock()
        handlers = dict(operation_handlers or {})
        unknown = set(handlers).difference(CURRENT_OPERATIONS | {"railgun.status", "swarm.inspect"})
        if unknown or any(not callable(handler) for handler in handlers.values()):
            raise ValueError("Terminal operation handlers are invalid")
        configured = {
            operation
            for resource in snapshot.resources
            for operation in resource.operations
        }
        missing = configured.difference(handlers)
        if "railgun.launch" in configured and "railgun.status" not in handlers:
            missing.add("railgun.status")
        if missing:
            raise ValueError(
                "Terminal snapshot enables an operation without a live adapter: "
                + ", ".join(sorted(missing))
            )
        self._operation_handlers = handlers

    @property
    def queue(self):
        return self._queue

    def _expire_locked(self):
        now = self._clock()
        for record in self._records.values():
            if record.state == "approved" and record.deadline is not None and now >= record.deadline:
                record.state = "expired"
                record.reason = "Connection approval expired"
                record.deadline = None

    def _prune_locked(self):
        self._expire_locked()
        while len(self._records) >= MAX_CONNECTION_RECORDS:
            removable = next(
                (
                    request_id
                    for request_id, record in self._records.items()
                    if record.state in {"denied", "expired", "revoked"}
                ),
                None,
            )
            if removable is None:
                raise ValueError("Terminal connection table is full")
            self._records.pop(removable)

    def _record_for(self, request_id, client_secret):
        request_id = _plain(request_id, "Request ID", maximum=128)
        digest = _secret_digest(client_secret)
        record = self._records.get(request_id)
        if record is None or not secrets.compare_digest(record.secret_digest, digest):
            raise PermissionError("Connection request identity did not match")
        return record

    def handle(self, method, params):
        allowed_methods = _BASE_CLIENT_METHODS | set(self._operation_handlers)
        if not isinstance(method, str) or method not in allowed_methods:
            raise PermissionError("Operation is not available from Terminal access")
        if method in {"swarms.list", "railgun.launch", "railgun.status", "agents.list", "logs.read", "swarm.inspect", "sessions.list", "sessions.open"}:
            return self._handle_remote(method, params)
        with self._lock:
            if self._closed:
                raise PermissionError("Terminal access is locked")
            self._expire_locked()
            if method == "terminal.status":
                _exact_params(params, ())
                return {
                    "mode": "terminal_connection_approval",
                    "accepting_requests": True,
                    "pending_requests": sum(
                        record.state == "pending" for record in self._records.values()
                    ),
                    "active_connections": sum(
                        record.state == "approved" for record in self._records.values()
                    ),
                    "operations_available": [],
                }
            if method == "connection.request":
                _exact_params(params, {"request_id", "client_label", "client_secret"})
                return self._request(
                    params["request_id"], params["client_label"], params["client_secret"]
                )
            if method == "connection.status":
                _exact_params(params, {"request_id", "client_secret"})
                record = self._record_for(params["request_id"], params["client_secret"])
                return self._public_status(record)
            if method == "alerts.read":
                names = {"request_id", "client_secret", "deployment_id", "after", "limit"}
                if isinstance(params, dict) and "stream_id" in params:
                    names.add("stream_id")
                _exact_params(
                    params, names,
                )
                record = self._record_for(params["request_id"], params["client_secret"])
                return self._read_alerts(
                    record,
                    params["deployment_id"],
                    params["after"],
                    params["limit"],
                    params.get("stream_id"),
                )
            _exact_params(params, {"request_id", "client_secret"})
            record = self._record_for(params["request_id"], params["client_secret"])
            if record.state == "pending":
                try:
                    self._queue.resolve(record.request.request_id, False, "client disconnected")
                except PermissionError:
                    pass
            record.state = "revoked"
            record.reason = "Client disconnected"
            record.deadline = None
            return self._public_status(record)

    def _request(self, request_id, client_label, client_secret):
        request_id = _plain(request_id, "Request ID", maximum=128)
        client_label = _plain(client_label, "Client label", maximum=160)
        digest = _secret_digest(client_secret)
        existing = self._records.get(request_id)
        if existing is not None:
            if not secrets.compare_digest(existing.secret_digest, digest):
                raise PermissionError("Request ID is already bound to another client secret")
            if existing.request.client_label != client_label:
                raise PermissionError("Request ID is already bound to another client label")
            return self._public_status(existing)
        self._prune_locked()
        operations = tuple(
            sorted({operation for resource in self.snapshot.resources for operation in resource.operations})
        )
        request = ConnectionApprovalRequest(
            request_id=request_id,
            client_label=client_label,
            vault_label=self.snapshot.vault_label,
            vault_revision=self.snapshot.vault_revision,
            resources=self.snapshot.resources,
            operations=operations,
            lifetime_seconds=self.snapshot.approval_lifetime_seconds,
        )
        record = _ConnectionRecord(request=request, secret_digest=digest)
        self._records[request_id] = record
        try:
            self._queue.enqueue(request)
        except RuntimeError as exc:
            self._records.pop(request_id, None)
            raise ValueError("Terminal approval queue is full") from exc
        return self._public_status(record)

    def next_approval(self):
        with self._lock:
            if self._closed:
                return None
            return self._queue.next()

    def resolve(self, request_id, allowed, reason):
        with self._lock:
            if self._closed:
                raise PermissionError("Terminal access is locked")
            record = self._records.get(request_id)
            if record is None or record.state != "pending":
                raise PermissionError("Approval request is no longer pending")
            self._queue.resolve(request_id, allowed, reason)
            if allowed:
                record.state = "approved"
                record.reason = "Operator approved connection"
                record.deadline = self._clock() + self.snapshot.approval_lifetime_seconds
            else:
                record.state = "denied"
                record.reason = reason
                record.deadline = None
            return self._public_status(record)

    def _public_status(self, record):
        from .tool_routes import permitted_calls
        remaining = None
        if record.state == "approved" and record.deadline is not None:
            remaining = max(0, int(record.deadline - self._clock()))
        return {
            "request_id": record.request.request_id,
            "state": record.state,
            "reason": record.reason,
            "remaining_seconds": remaining,
            "vault_revision": record.request.vault_revision if record.state == "approved" else None,
            "tool_usage_hint": (
                "resources below are deployment scopes, NOT MCP resource URIs. "
                "Call the named tools in tool_calls using their arguments. "
                "For deferred tools, search the exact tool_name and invoke the full name returned by your host. "
                "Do not invent res:// paths or use read_resource for swarm data."
            ),
            "operations_available": (
                list(record.request.operations) if record.state == "approved" else []
            ),
            "resources": ([
                {"deployment_id": r.deployment_id, "label": r.label,
                 "operations": list(r.operations),
                 "tool_calls": permitted_calls(r.deployment_id, r.operations),
                 "inspection_available": {"agents.list", "logs.read"}.issubset(r.operations),
                 **({"inspection_unavailable_reason": "Swarm inspection requires BOTH agents.list and logs.read for this deployment."}
                    if not {"agents.list", "logs.read"}.issubset(r.operations) else {}),
                 **({"fixed_destination": r.fixed_destination} if r.fixed_destination else {})}
                for r in record.request.resources if r.operations
            ] if record.state == "approved" else []),
        }

    def _handle_remote(self, method, params):
        operation = "railgun.launch" if method == "railgun.status" else method
        names = {"request_id", "client_secret", "deployment_id"}
        if method.startswith("railgun."):
            names.add("operation_id")
        if method == "logs.read":
            names.add("agent_id")
        _exact_params(params, names)
        deployment_id = _plain(params["deployment_id"], "Deployment ID", maximum=256)
        operation_id = params.get("operation_id")
        if method == "logs.read":
            from .swarm_inspection import agent_identifier
            agent_identifier(params["agent_id"])
        if method.startswith("railgun.") and (
            not isinstance(operation_id, str) or not re.fullmatch(r"[a-f0-9]{32}", operation_id)
        ):
            raise ValueError("operation_id must be a 32-character lowercase hex ID; reuse it for retries")
        with self._lock:
            if self._closed:
                raise PermissionError("Terminal access is locked")
            self._expire_locked()
            record = self._record_for(params["request_id"], params["client_secret"])
            resource = next((r for r in record.request.resources if r.deployment_id == deployment_id), None)
            if record.state != "approved":
                raise PermissionError("Connection is not approved")
            required = {"agents.list", "logs.read"} if method == "swarm.inspect" else {operation}
            if resource is None or not required.issubset(resource.operations):
                raise PermissionError(f"{operation} is not allowed for this deployment")

        lease = self._operation_lease(record, method, deployment_id)

        # No network while holding the lifecycle lock: the operator must always
        # be able to lock/revoke access, even during an unresponsive SSH call.
        from .swarm_inspection import DiagnosticReadError
        try:
            if method in {"swarms.list", "agents.list", "swarm.inspect"}:
                value = self._operation_handlers[method](deployment_id, lease)
            elif method == "logs.read":
                value = self._operation_handlers[method](deployment_id, params["agent_id"], lease)
            elif method in {"sessions.list", "sessions.open"}:
                value = self._operation_handlers[method](method, deployment_id,
                    {"request_id": params["request_id"], "client_secret": params["client_secret"]}, lease)
            else:
                value = self._operation_handlers[method](deployment_id, operation_id,
                    record.request.request_id, lease)
        except PermissionError:
            raise PermissionError("Connection approval ended or the operation was denied") from None
        except DiagnosticReadError as exc:
            # These errors contain fixed guidance only. Preserve it through the
            # HTTP boundary instead of replacing it with a generic failure.
            raise DiagnosticReadError(str(exc)) from None
        except Exception:
            raise RuntimeError("The fixed-target operation could not complete; no raw server output is exposed") from None
        if not lease():
            raise PermissionError("Connection approval ended during the operation")
        from .remote_access import public_inventory_page, public_launch_status
        if method == "swarms.list":
            return public_inventory_page(deployment_id, value)
        if method in {"agents.list", "logs.read", "swarm.inspect"}:
            from .swarm_inspection import public_diagnostic_page
            return public_diagnostic_page(method, deployment_id, value, params.get("agent_id"))
        if method in {"sessions.list", "sessions.open"}:
            from .cockpit_sessions import public_session_page
            return public_session_page(deployment_id, value)
        return public_launch_status(deployment_id, operation_id, value)

    def _operation_lease(self, record, method, deployment_id):
        """Adapter hook; live Phoenix also checks its vault-owned authority."""
        def lease():
            with self._lock:
                self._expire_locked()
                return not self._closed and record.state == "approved"
        return lease

    def _read_alerts(self, record, deployment_id, after, limit, stream_id=None):
        if record.state != "approved":
            raise PermissionError("Connection is not approved")
        deployment_id = _plain(deployment_id, "Deployment ID", maximum=256)
        if type(after) is not int or after < 0:
            raise ValueError("after must be a nonnegative integer")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be an integer from 1 to 200")
        if stream_id is not None:
            _plain(stream_id, "Stream ID", minimum=32, maximum=32)
        resource = next(
            (
                item
                for item in record.request.resources
                if item.deployment_id == deployment_id
            ),
            None,
        )
        if resource is None or "alerts.read" not in resource.operations:
            raise PermissionError("alerts.read is not allowed for this deployment")
        try:
            page = self._operation_handlers["alerts.read"](
                deployment_id, after, limit
            )
        except AlertReadError:
            raise
        except Exception as exc:
            raise RuntimeError("The alert source could not complete the read") from exc
        self._expire_locked()
        if record.state != "approved":
            raise PermissionError("Connection approval expired during read")
        page = public_alert_page(deployment_id, after, limit, page)
        source = page.get("source")
        if source and ((after > 0 and stream_id is None)
                       or (stream_id is not None and stream_id != source["stream_id"])):
            raise ValueError("Alert stream changed or stream_id is missing; restart with after=0")
        return page

    def active_alert_grants(self):
        """Private worker lease view, not a client operation or credential export."""
        with self._lock:
            if self._closed:
                return {}
            self._expire_locked()
            grants = {}
            for record in self._records.values():
                if record.state == "approved":
                    for resource in record.request.resources:
                        if "alerts.read" in resource.operations:
                            grants.setdefault(resource.deployment_id, []).append(
                                (record.request.request_id, record.deadline))
            return {key: tuple(value) for key, value in grants.items()}

    def counts(self):
        with self._lock:
            self._expire_locked()
            return {
                "pending": sum(record.state == "pending" for record in self._records.values()),
                "active": sum(record.state == "approved" for record in self._records.values()),
            }

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._queue.revoke_all("terminal locked")
            for record in self._records.values():
                if record.state in {"pending", "approved"}:
                    record.state = "revoked"
                    record.reason = "Terminal locked"
                    record.deadline = None
