"""Parent-owned, read-only session adapter over Phoenix's verified transport.

MCP supplies only a permitted deployment and, for logs, an agent ID. This
adapter constructs every packet itself. No vault, packet, handler, path, or
connector selection is exposed to the caller. The one vault authority remains
the permission owner; session/runtime bindings narrow each admitted read.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import base64
import json
import re
import threading
import time
from types import SimpleNamespace
import uuid

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from phoenix_terminal.swarm_inspection import DiagnosticReadError
from .models import AccessDenied


_DIAGNOSTIC_ERRORS = {
    "BUSY": "Log Streamer read capacity is occupied.",
    "INVALID_LOCAL_RUNTIME": "Log Streamer could not identify its local runtime.",
    "UNSUPPORTED_DIAGNOSTIC_OPERATION": "The server does not support this diagnostic operation.",
    "RUNTIME_CHANGED": "The swarm boot changed; reconnect deliberately.",
    "BOOT_UNAVAILABLE_OR_AMBIGUOUS": "The server could not observe exactly one current swarm boot.",
    "AGENT_NOT_OBSERVED": "The requested agent was not observed in the bound swarm boot.",
    "TREE_RUNTIME_MISMATCH": "Matrix tree metadata and Log Streamer refer to different boots; update Matrix routing/core and reconnect.",
    "RESPONSE_LIMIT_EXCEEDED": "The diagnostic snapshot exceeded the server response limit.",
    "DIAGNOSTIC_READ_FAILED": "The server diagnostic reader failed; check Log Streamer's AI-DIAGNOSTIC entries.",
    "DIAGNOSTICS_UNAVAILABLE_OR_BOOT_CHANGED": "The server returned a legacy catch-all failure; update Matrix/Log Streamer/core for specific failure codes.",
}

_TRANSPORT_ERRORS = {
    "WSS_TRUST_FAILED": "WebSocket peer trust failed.",
    "WSS_DENIED": "WebSocket authentication or access was denied.",
    "WSS_REJECTED": "The server rejected the WebSocket connection.",
    "WSS_CONFIGURATION_INVALID": "WebSocket configuration or credentials are invalid.",
    "WSS_CONNECT_TIMEOUT": "The WebSocket reply channel did not become ready in time.",
    "WSS_UNAVAILABLE": "The WebSocket reply channel is temporarily unavailable.",
    "EGRESS_TRUST_FAILED": "HTTPS peer trust failed.",
    "EGRESS_DENIED": "HTTPS authentication or access was denied.",
    "EGRESS_REJECTED": "The server rejected the HTTPS command.",
    "EGRESS_CONFIGURATION_INVALID": "HTTPS configuration or credentials are invalid.",
    "EGRESS_SESSION_ENDED": "The HTTPS session ended before sending.",
    "EGRESS_QUEUE_FAILED": "Phoenix could not admit the HTTPS command.",
    "EGRESS_INVALID_ACK": "HTTPS did not return a valid bounded acceptance response.",
    "EGRESS_TEMPORARY": "HTTPS reported a temporary server failure or throttling.",
    "EGRESS_TIMEOUT": "The HTTPS command timed out.",
    "EGRESS_UNAVAILABLE": "The HTTPS command channel is temporarily unavailable.",
    "EGRESS_ACK_TIMEOUT": "No HTTPS acceptance receipt arrived in time.",
    "SIGNED_REPLY_TIMEOUT": "HTTPS accepted the command, but no verified diagnostic reply arrived in time.",
    "INVALID_DIAGNOSTIC_RESPONSE": "The verified diagnostic response was invalid or stale.",
    "UNKNOWN_DIAGNOSTIC_FAILURE": "The server returned an unrecognized diagnostic failure.",
}
_RETRYABLE = frozenset({"BUSY", "WSS_CONNECT_TIMEOUT", "WSS_UNAVAILABLE",
    "EGRESS_TEMPORARY", "EGRESS_TIMEOUT", "EGRESS_UNAVAILABLE",
    "EGRESS_ACK_TIMEOUT", "SIGNED_REPLY_TIMEOUT"})
CONNECT_ATTEMPTS, CONNECT_DEADLINE, CONNECT_ATTEMPT_SECONDS = 3, 50, 14
CONNECT_RETRY_DELAYS = (2, 4)


class LiveReadFailure(DiagnosticReadError):
    def __init__(self, operation, code):
        self.code = code if code in _DIAGNOSTIC_ERRORS or code in _TRANSPORT_ERRORS else "UNKNOWN_DIAGNOSTIC_FAILURE"
        reason = _DIAGNOSTIC_ERRORS.get(self.code) or _TRANSPORT_ERRORS[self.code]
        super().__init__(f"Live diagnostic {operation} failed [{self.code}]: {reason}")


@dataclass
class ReadTicket:
    operation: str
    lease: object
    generation: int
    runtime_id: str
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    token: str = field(default_factory=lambda: uuid.uuid4().hex)
    done: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None
    error: str | None = None
    error_code: str | None = None
    delivery_done: threading.Event = field(default_factory=threading.Event)
    delivery_state: str = "not_received"
    delivery_error: str | None = None
    http_status: int | None = None


def live_target(data, deployment_id):
    from phoenix_terminal.vault_console import public_inventory
    from phoenix_terminal.bridge.deployment_view import agent_nodes
    raw = data["deployments"][deployment_id]
    universe = raw.get("universe") or raw.get("name") or raw.get("label")
    if not isinstance(universe, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", universe):
        raise ValueError("A live session requires a saved universe name")
    source = agent_nodes(raw.get("agents", []))
    nodes = [{key: deepcopy(node[key]) for key in ("universal_id", "name", "serial", "connection")
              if key in node} for node in source]
    ids = [node.get("universal_id") for node in nodes]
    if any(not isinstance(uid, str) for uid in ids) or len(set(ids)) != len(ids):
        raise ValueError("Saved agent identities must be unique")
    # Keep credentials only for this deployment in the parent. No SSH, SMTP,
    # dynamic connector loading, source bundles or unrelated vault sections.
    ingress = next((n for n in nodes if (n.get("connection") or {}).get("channel") == "payload.reception"
                    and n["connection"].get("proto") == "wss"), None)
    egress = next((n for n in nodes if (n.get("connection") or {}).get("channel") == "outgoing.command"
                   and n["connection"].get("proto") == "https"), None)
    streamers = [n for n in nodes if n.get("name") == "log_streamer"]
    matrices = [n for n in nodes if n.get("name") == "matrix"]
    if ingress is None or egress is None or len(streamers) != 1 or len(matrices) != 1:
        raise ValueError("Live AI inspection requires saved WSS ingress, HTTPS egress, Matrix and one Log Streamer")
    selected = {ingress["universal_id"], egress["universal_id"]}
    for node in nodes:
        node.pop("children", None)
        node.pop("config", None)
        if node["universal_id"] not in selected:
            node["connection"] = {}
    key = base64.b64decode(raw.get("swarm_key", ""), validate=True)
    if len(key) not in (16, 24, 32):
        raise ValueError("Saved diagnostic log key is invalid")
    certificate_ids = selected | {streamers[0]["universal_id"], matrices[0]["universal_id"]}
    certs = {uid: deepcopy(raw.get("certs", {}).get(uid, {})) for uid in certificate_ids}
    for uid in (streamers[0]["universal_id"], matrices[0]["universal_id"]):
        signing = certs[uid].get("signing", {})
        if not signing.get("pubkey") or not signing.get("remote_privkey"):
            raise ValueError("Saved Matrix and Log Streamer callback certificates are required")
    return SimpleNamespace(universe=universe, profile_json="{}", log_key=key,
        expected=list(public_inventory(data)[deployment_id]["agents"].values()),
        deployment={"id": deployment_id, "name": universe, "agents": nodes,
                    "certs": certs},
        ingress_uid=ingress["universal_id"], egress_uid=egress["universal_id"],
        streamer_uid=streamers[0]["universal_id"], matrix_uid=matrices[0]["universal_id"])


class SessionDiagnostics(QObject):
    incoming = pyqtSignal(object)
    tree_incoming = pyqtSignal(object)
    delivery_incoming = pyqtSignal(object)

    def __init__(self, target, session_id, lease, parent):
        super().__init__(parent)
        self.target, self.session_id, self.open_lease = target, session_id, lease
        self.connection_id = lease.connection_id
        self.runtime_id, self.generation = "", 0
        self.closed, self.ctx = False, None
        self.connected = threading.Event()
        self.pending, self.tree = {}, []
        self.ingress_error, self.connection_readiness = None, None
        self.tree_coverage = {"state": "not_received", "observed_at": None,
                              "source": None, "truncated": False}
        self._lock = threading.RLock()
        self.incoming.connect(self._receive, Qt.ConnectionType.QueuedConnection)
        self.tree_incoming.connect(self._receive_tree, Qt.ConnectionType.QueuedConnection)
        self.delivery_incoming.connect(self._receive_delivery, Qt.ConnectionType.QueuedConnection)

    def start(self):
        from matrix_gui.modules.net.deployment_connector import _connect_single
        from matrix_gui.config.boot.globals import get_sessions
        from matrix_gui.core.dispatcher.inbound_dispatcher import InboundDispatcher
        from matrix_gui.core.dispatcher.outbound_dispatcher import OutboundDispatcher
        connected = _connect_single(deepcopy(self.target.deployment), self.session_id,
                                    self.target.deployment["id"], managed_startup=True)
        self.ctx = connected if getattr(connected, "bus", None) else get_sessions().get(self.session_id)
        if not connected or not self.ctx or not getattr(self.ctx, "bus", None):
            raise RuntimeError("Live session could not initialize")
        self.inbound = InboundDispatcher(self.ctx.bus, self.session_id)
        self.outbound = OutboundDispatcher(self.ctx.bus, self.session_id)
        channels = self.ctx.channels
        self.inbound.set_inbound_connector(channels[self.target.ingress_uid])
        self.outbound.set_outbound_connector(channels[self.target.egress_uid])
        self.ctx.bus.on("inbound.verified.ai_diagnostic.update", self._incoming)
        self.ctx.bus.on("inbound.verified.agent_tree_master.update", self._tree_incoming)
        self.ctx.bus.on("channel.status", self._channel_status)
        self.ctx.bus.on("channel.failure", self._channel_failure)
        self.ctx.bus.on("channel.delivery", self._delivery)
        failure = getattr(self.ctx, "failures", {}).get(self.target.ingress_uid)
        if failure:
            self._channel_failure(self.session_id, self.target.ingress_uid, failure)
        if self.ctx.status.get(self.target.ingress_uid) == "connected":
            self.connected.set()

    def _channel_status(self, session_id, channel, status, **_):
        if session_id == self.session_id and channel == self.target.ingress_uid:
            if status == "connected" and not self.closed:
                self.connected.set()
            else:
                self.connected.clear()

    def _channel_failure(self, session_id, channel, error_code, **_):
        if (not self.closed and session_id == self.session_id and channel == self.target.ingress_uid
                and error_code in _TRANSPORT_ERRORS):
            with self._lock:
                # A later status event must not erase a trust/access failure.
                if self.ingress_error is None or self.ingress_error in _RETRYABLE:
                    self.ingress_error = error_code

    def transport_failure(self):
        with self._lock:
            return self.ingress_error

    def _delivery(self, session_id, channel, **receipt):
        if session_id == self.session_id and channel == self.target.egress_uid and not self.closed:
            self.delivery_incoming.emit(deepcopy(receipt))

    def _receive_delivery(self, receipt):
        if self.closed or not isinstance(receipt, dict):
            return
        with self._lock:
            ticket = self.pending.get(receipt.get("delivery_id"))
            if (ticket is None or ticket.generation != self.generation or ticket.delivery_done.is_set()
                    or not ticket.lease() or not self.open_lease()):
                return
            state, status, error = receipt.get("state"), receipt.get("http_status"), receipt.get("error_code")
            if state == "accepted" and type(status) is int and status == 200 and error is None:
                ticket.delivery_state, ticket.http_status = state, status
            elif state == "failed" and isinstance(error, str) and error in _TRANSPORT_ERRORS:
                ticket.delivery_state, ticket.delivery_error = state, error
                ticket.http_status = status if type(status) is int and 100 <= status <= 599 else None
            else:
                return
            ticket.delivery_done.set()

    def readiness(self):
        with self._lock:
            return deepcopy(self.connection_readiness)

    def prepare_ingress(self, lease):
        """One supervised-by-Connect launch; never use the unlimited monitor."""
        if self.closed or not self.ctx or not lease() or not self.open_lease():
            raise AccessDenied("Live session approval ended")
        if not self.connected.is_set():
            failure = self.transport_failure()
            if failure and failure not in _RETRYABLE:
                raise LiveReadFailure("bind", failure)
            launcher = self.ctx.group.get("connection_launcher")
            lease.commit(lambda: launcher.launch(self.target.ingress_uid, fire_catapult=True))

    def _incoming(self, payload, session_id, **_):
        if session_id == self.session_id and not self.closed and self._bounded(payload):
            self.incoming.emit(deepcopy(payload))

    def _tree_incoming(self, payload, session_id, **_):
        if session_id == self.session_id and not self.closed and self._bounded(payload):
            self.tree_incoming.emit(deepcopy(payload))

    @staticmethod
    def _bounded(payload):
        try:
            return len(json.dumps(payload).encode("utf-8")) <= 512 * 1024
        except (ValueError, TypeError, RecursionError):
            return False

    def binding(self):
        with self._lock:
            return {"session_id": self.session_id, "runtime_id": self.runtime_id,
                    "generation": self.generation, "transport": "phoenix_session"}

    def current(self, binding):
        with self._lock:
            return not self.closed and binding == self.binding()

    def submit(self, operation, lease, agent_id=None):
        from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
        from phoenix_terminal.swarm_inspection import DiagnosticReadError
        if operation not in {"bind", "agents", "logs", "inspect"}:
            raise AccessDenied("Unsupported live diagnostic operation")
        if not self.open_lease() or not lease() or lease.connection_id != self.connection_id:
            raise AccessDenied("Live session approval ended")
        if not self.connected.is_set():
            raise DiagnosticReadError("Live WSS reply channel is not connected; no SSH fallback was used")
        with self._lock:
            if self.closed or len(self.pending) >= 4:
                raise AccessDenied("Live session closed or read capacity reached")
            if operation != "bind" and not self.runtime_id:
                raise AccessDenied("Live session has no verified boot binding")
            if operation == "logs" and agent_id not in {a["universal_id"] for a in self.target.expected}:
                raise AccessDenied("Agent is outside the saved diagnostic inventory")
            ticket = ReadTicket(operation, lease, self.generation, self.runtime_id)
            self.pending[ticket.request_id] = ticket
        body = {"target_universal_id": self.target.streamer_uid, "session_id": self.session_id,
                "token": ticket.token, "request_id": ticket.request_id,
                "operation": operation, "runtime_id": "" if operation == "bind" else ticket.runtime_id}
        if agent_id is not None:
            body["agent_id"] = agent_id
        packet = Packet()
        packet.set_data({"handler": "cmd_service_request", "content":
                         {"service": "hive.log_streamer", "payload": body}})
        try:
            # Crypto wrapping and connector queue admission are local; socket I/O
            # runs in connector workers. Revocation cannot undo an admitted read.
            lease.commit(lambda: self.ctx.bus.emit("outbound.message", session_id=self.session_id,
                         channel="outgoing.command", packet=packet, delivery_id=ticket.request_id))
        except Exception:
            self.cancel(ticket)
            raise
        return ticket

    def cancel(self, ticket):
        with self._lock:
            self.pending.pop(ticket.request_id, None)
            ticket.result = None
            ticket.error = "Read canceled or approval ended"
            ticket.done.set()

    def _receive(self, payload):
        if self.closed or not isinstance(payload, dict) or payload.get("verified_sender") != self.target.streamer_uid:
            return
        content = payload.get("content")
        if (not isinstance(content, dict)
                or content.get("session_id") != self.session_id
                or not isinstance(content.get("request_id"), str)
                or not re.fullmatch(r"[a-f0-9]{32}", content["request_id"])):
            return
        with self._lock:
            ticket = self.pending.get(content.get("request_id"))
        if (ticket is None or content.get("token") != ticket.token or content.get("operation") != ticket.operation
                or not ticket.lease() or not self.open_lease()):
            return
        with self._lock:
            if self.closed or ticket.generation != self.generation:
                self.cancel(ticket)
                return
            if ticket.done.is_set():
                return
            if (set(content) != {"session_id", "token", "request_id", "operation", "ok", "error", "document"}
                    or type(content.get("ok")) is not bool
                    or (content["ok"] and content.get("error") is not None)
                    or (not content["ok"] and content.get("document") is not None)):
                ticket.error_code = "INVALID_DIAGNOSTIC_RESPONSE"
                ticket.error = str(LiveReadFailure(ticket.operation, ticket.error_code))
                ticket.done.set()
                return
            if content.get("ok") is not True:
                code = content.get("error")
                if not isinstance(code, str) or code not in _DIAGNOSTIC_ERRORS:
                    code = "UNKNOWN_DIAGNOSTIC_FAILURE"
                ticket.error_code = code
                ticket.error = str(LiveReadFailure(ticket.operation, code))
            else:
                doc = content.get("document")
                boot = doc.get("boot_id") if isinstance(doc, dict) else None
                if (not isinstance(boot, str) or not re.fullmatch(r"[0-9_]{1,32}", boot)
                        or doc.get("universe") != self.target.universe
                        or (self.runtime_id and boot != self.runtime_id)):
                    self.invalidate()
                    return
                previous_boot = self.runtime_id
                try:
                    observed = datetime.fromisoformat(doc["observed_at"])
                    age = (datetime.now(timezone.utc) - observed).total_seconds()
                    if type(doc.get("version")) is not int or doc["version"] != 1 or not -10 <= age <= 120:
                        raise ValueError("Stale observation")
                    if not self.runtime_id:
                        self.runtime_id = boot
                    snapshot = doc.get("agent_tree_snapshot")
                    if snapshot is not None:
                        if snapshot.get("runtime_id") != boot:
                            raise ValueError("Tree boot mismatch")
                        self._set_tree(snapshot["nodes"], {"state": snapshot["state"],
                            "observed_at": snapshot["observed_at"], "source": "matrix_snapshot",
                            "truncated": snapshot["truncated"]})
                except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                    self.runtime_id = previous_boot
                    ticket.error_code = "INVALID_DIAGNOSTIC_RESPONSE"
                    ticket.error = str(LiveReadFailure(ticket.operation, ticket.error_code))
                else:
                    ticket.result = deepcopy(doc)
            # Retain correlation until both the HTTPS receipt and signed reply
            # have arrived. Either can win the network race; cancel removes it.
            ticket.done.set()

    def _receive_tree(self, payload):
        if (self.closed or not self.open_lease() or not isinstance(payload, dict)
                or payload.get("verified_sender") != self.target.matrix_uid):
            return
        boot = payload.get("runtime_id")
        if not isinstance(boot, str) or not re.fullmatch(r"[0-9_]{1,32}", boot):
            return  # An older unbound tree cannot replace current evidence.
        with self._lock:
            if self.runtime_id and boot != self.runtime_id:
                self.invalidate()
                return
            try:
                stamp = datetime.fromtimestamp(payload["timestamp"], timezone.utc)
                if not -10 <= (datetime.now(timezone.utc) - stamp).total_seconds() <= 120:
                    return
                nodes, stack = [], [(payload.get("content"), None)]
                from phoenix_terminal.swarm_inspection import agent_identifier, _safe_message
                while stack and len(nodes) < 256:
                    node, parent = stack.pop()
                    uid = agent_identifier(node.get("universal_id"))
                    children = node.get("children", [])
                    if not isinstance(children, list) or len(children) > 256:
                        return
                    nodes.append({"agent_id": uid, "parent_id": parent,
                                  "name": _safe_message(node.get("name") or uid)[:128]})
                    stack.extend((child, uid) for child in reversed(children))
                previous_boot = self.runtime_id
                self.runtime_id = boot
                try:
                    self._set_tree(nodes, {"state": "available", "observed_at": stamp.isoformat(),
                                   "source": "matrix_broadcast", "truncated": bool(stack)})
                except ValueError:
                    self.runtime_id = previous_boot
                    raise
            except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
                return

    def _set_tree(self, nodes, coverage):
        from phoenix_terminal.swarm_inspection import session_evidence_context
        projected = session_evidence_context({"session_binding": self.binding(),
                    "agent_tree": nodes, "agent_tree_coverage": coverage}, {})
        self.tree = projected["agent_tree"]
        self.tree_coverage = projected["agent_tree_coverage"]

    def tree_evidence(self):
        with self._lock:
            coverage = deepcopy(self.tree_coverage)
            if coverage["observed_at"] is not None:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(coverage["observed_at"])).total_seconds()
                if age > 120:
                    coverage["state"] = "stale"
            return deepcopy(self.tree), coverage

    def invalidate(self):
        with self._lock:
            self.generation += 1
            self.closed = True
            self.connected.clear()
            self.tree.clear()
            for ticket in tuple(self.pending.values()):
                self.cancel(ticket)

    def close(self):
        self.invalidate()
        if self.ctx is None:
            return
        ctx, self.ctx = self.ctx, None
        from matrix_gui.core.connector_bus import ConnectorBus
        from matrix_gui.config.boot.globals import get_sessions
        if getattr(ctx, "bus", None):
            ctx.bus.clear()
        for event, handler in getattr(ctx, "_bus_refs", ()):
            ConnectorBus.get(self.session_id).off(event, handler)
        ConnectorBus.release(self.session_id)
        get_sessions().destroy(self.session_id)
        def dispose():
            try:
                launcher = ctx.group.get("connection_launcher")
                if launcher is not None:
                    launcher.destroy_all()
            finally:
                ctx.group.get("deployment", {}).clear()
        threading.Thread(target=dispose, name="AI-session-close", daemon=True).start()


class LiveSessionOperations:
    def __init__(self, runtime, targets):
        self.runtime, self.targets = runtime, targets

    def _progress(self, deployment_id, lease, stage, attempt, error_code=None):
        self.runtime.evidence_ready.emit((lease, deployment_id, {"connection_readiness": {
            "state": "retrying" if stage == "retrying" else "waiting", "stage": stage,
            "attempts": attempt, "max_attempts": CONNECT_ATTEMPTS,
            "timeout_seconds": CONNECT_DEADLINE, "last_error_code": error_code}}))

    @staticmethod
    def _check(session, lease, operation):
        if not lease() or not session.open_lease() or session.closed:
            raise AccessDenied("Live read approval or session ended; no retry was made")
        failure = session.transport_failure()
        if failure and failure not in _RETRYABLE:
            raise LiveReadFailure(operation, failure)

    def _read_once(self, deployment_id, operation, lease, agent_id, session, deadline, attempt=None):
        self._check(session, lease, operation)
        if attempt is not None:
            self._progress(deployment_id, lease, "waiting_websocket", attempt)
            self.runtime.dispatcher.call("diagnostic.prepare", {
                "deployment_id": deployment_id, "lease": lease})
        while not session.connected.is_set():
            self._check(session, lease, operation)
            if time.monotonic() >= deadline:
                raise LiveReadFailure(operation, session.transport_failure() or "WSS_CONNECT_TIMEOUT")
            session.connected.wait(min(0.1, max(0, deadline - time.monotonic())))
        self._check(session, lease, operation)
        if time.monotonic() >= deadline:
            raise LiveReadFailure(operation, "EGRESS_ACK_TIMEOUT")
        if attempt is not None:
            self._progress(deployment_id, lease, "waiting_https", attempt)
        packet = self.runtime.dispatcher.call("diagnostic.read", {"deployment_id": deployment_id,
                         "operation": operation, "agent_id": agent_id, "lease": lease})
        current_session, ticket = packet["session"], packet["ticket"]
        try:
            if current_session is not session:
                raise AccessDenied("Live session changed during the read; no retry was made")
            stage = "waiting_https"
            while True:
                self._check(session, lease, operation)
                if ticket.delivery_done.is_set() and ticket.delivery_state != "accepted":
                    raise LiveReadFailure(operation, ticket.delivery_error)
                if ticket.done.is_set() and ticket.error:
                    raise LiveReadFailure(operation, ticket.error_code)
                if ticket.done.is_set() and ticket.delivery_done.is_set():
                    if time.monotonic() >= deadline:
                        raise LiveReadFailure(operation, "SIGNED_REPLY_TIMEOUT")
                    if not session.connected.is_set():
                        raise LiveReadFailure(operation, "WSS_UNAVAILABLE")
                    if not session.current({"session_id": session.session_id, "runtime_id": ticket.result["boot_id"],
                                           "generation": ticket.generation, "transport": "phoenix_session"}):
                        raise AccessDenied("Live session binding changed; no retry was made")
                    return deepcopy(ticket.result), {"http_status": ticket.http_status}
                if time.monotonic() >= deadline:
                    raise LiveReadFailure(operation, "SIGNED_REPLY_TIMEOUT" if ticket.delivery_done.is_set()
                                          else "EGRESS_ACK_TIMEOUT")
                if ticket.delivery_done.is_set() and stage != "waiting_signed_reply":
                    stage = "waiting_signed_reply"
                    if attempt is not None:
                        self._progress(deployment_id, lease, stage, attempt)
                # The worker waits; the Qt UI and revocation timer keep running.
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        finally:
            session.cancel(ticket)  # Late replies/receipts cannot satisfy another attempt.

    def _read(self, deployment_id, operation, lease, agent_id=None, *, connect=False):
        deadline = time.monotonic() + (CONNECT_DEADLINE if connect else 25)
        session = self.runtime.dispatcher.call("diagnostic.session", {
            "deployment_id": deployment_id, "lease": lease})["session"]
        limit = CONNECT_ATTEMPTS if connect else 1
        for attempt in range(1, limit + 1):
            self._check(session, lease, operation)
            attempt_deadline = min(deadline, time.monotonic() + CONNECT_ATTEMPT_SECONDS) if connect else deadline
            try:
                document, receipt = self._read_once(deployment_id, operation, lease, agent_id,
                    session, attempt_deadline, attempt if connect else None)
            except LiveReadFailure as failure:
                failure.attempts = attempt
                if not connect or failure.code not in _RETRYABLE:
                    raise
                if attempt == limit or time.monotonic() >= deadline:
                    failure.args = (f"Connect failed after {attempt}/{limit} attempts "
                        f"(maximum {CONNECT_DEADLINE} seconds) [{failure.code}]; no SSH fallback was used. "
                        "Report this limit and stop; the operator must decide whether to reconnect.",)
                    raise failure from None
                self._progress(deployment_id, lease, "retrying", attempt, failure.code)
                pause_until = min(deadline, time.monotonic() + CONNECT_RETRY_DELAYS[attempt - 1])
                while time.monotonic() < pause_until:
                    self._check(session, lease, operation)
                    time.sleep(min(0.1, max(0, pause_until - time.monotonic())))
            else:
                if connect:
                    with session._lock:
                        self._check(session, lease, operation)
                        session.connection_readiness = {"state": "ready", "attempts": attempt,
                            "max_attempts": limit, "timeout_seconds": CONNECT_DEADLINE,
                            "ingress": "wss_connected", "egress": "https_accepted",
                            "http_status": receipt["http_status"], "signed_reply_verified": True,
                            "runtime_id": document["boot_id"], "observed_at": document["observed_at"]}
                return document, session

    def bind(self, deployment_id, lease, *, connect=False):
        return self._read(deployment_id, "bind", lease, connect=connect)[1]

    def _diagnostic(self, deployment_id, operation, lease, agent_id=None):
        from phoenix_terminal.swarm_inspection import inventory_page, inspection_page, log_page
        session = self.runtime.dispatcher.call("diagnostic.session", {
            "deployment_id": deployment_id, "lease": lease})["session"]
        if (self.runtime.connect_in_progress(lease.connection_id, deployment_id)
                or (session.readiness() or {}).get("state") != "ready"):
            raise DiagnosticReadError("Wait for a permitted Phoenix Connect to return verified transport readiness before inspecting; no SSH fallback was used.")
        self.bind(deployment_id, lease)  # A fresh signed boot observation per read.
        document, session = self._read(deployment_id, operation, lease, agent_id)
        binding = session.binding()
        target = self.targets[deployment_id]
        if operation == "logs":
            result = log_page(deployment_id, target, agent_id, document)
        elif operation == "inspect":
            result = inspection_page(deployment_id, target, target.expected, document)
        else:
            result = inventory_page(deployment_id, target.universe, target.expected, document)
        if not session.current(binding) or not lease():
            raise AccessDenied("Session binding changed during evidence processing")
        result["session_binding"] = binding
        if operation != "logs":
            result["agent_tree"], result["agent_tree_coverage"] = session.tree_evidence()
        return result

    def agents(self, deployment_id, lease):
        return self._diagnostic(deployment_id, "agents", lease)

    def logs(self, deployment_id, agent_id, lease):
        return self._diagnostic(deployment_id, "logs", lease, agent_id)

    def inspect(self, deployment_id, lease):
        return self._diagnostic(deployment_id, "inspect", lease)

    def inventory(self, deployment_id, lease):
        report = self.agents(deployment_id, lease)
        return {"deployment_id": deployment_id, "universes": [{"universe": report["universe"],
                "status": "active", "agent_count": sum(r["process_count"] for r in report["agents"]),
                "rss_bytes": None, "cpu_percent": None}], "session_binding": report["session_binding"],
                "resource_metrics_available": False}

    def current(self, deployment_id, connection_id, binding):
        row = self.runtime.views.get((connection_id, deployment_id))
        return row is not None and row[4].current(binding)

    def close(self):
        for row in tuple(self.runtime.views.values()):
            row[4].close()
