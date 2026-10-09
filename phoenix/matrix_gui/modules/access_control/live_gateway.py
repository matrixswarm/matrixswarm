"""Live Phoenix adapter for the existing Gemma MCP protocol.

Only the parent owns credentials, signed grants and saved connector targets. HTTP
threads perform bounded read operations; Qt alone handles approval and views.
No native session subprocess, legacy action bridge or arbitrary panel is used.
"""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import re
import sys
import threading
import uuid

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from .models import AccessDenied, Permission, Target


SUPPORTED = frozenset({"swarms.list", "agents.list", "logs.read", "sessions.list", "sessions.open"})


def _load_terminal():
    # Prefer this checkout's sibling. A standalone Phoenix copy may use the
    # installed Phoenix Terminal package already used by Hermes.
    sibling = Path(__file__).resolve().parents[4] / "phoenix_terminal"
    if (sibling / "phoenix_terminal" / "__init__.py").is_file():
        sys.path.insert(0, str(sibling))
        try:
            package = importlib.import_module("phoenix_terminal")
        finally:
            sys.path.pop(0)
        if Path(package.__file__).resolve() != (sibling / "phoenix_terminal/__init__.py").resolve():
            raise RuntimeError("Another Phoenix Terminal checkout is loaded; restart Phoenix")
    else:
        importlib.import_module("phoenix_terminal")


_load_terminal()
from phoenix_terminal.connection_broker import TerminalConnectionBroker, TerminalSnapshot
from phoenix_terminal.connection_approval import ApprovalResource
from phoenix_terminal.bridge.qt_dispatcher import QtBridgeDispatcher
from phoenix_terminal.terminal_server import TerminalRequestServer
from .session_diagnostics import LiveSessionOperations, SessionDiagnostics, live_target
from phoenix_terminal.vault_console import public_inventory
from matrix_gui.modules.vault.terminal_access_policy import validate_policy, allows, deployment_ids, vault_revision


def _binding(vault):
    """Credential enrollment changes no saved target; policy edits do."""
    data = vault.read()
    data.pop("access_control", None)
    data["access_control"] = vault.access_control.policy()
    return vault_revision(data)


class _Lease:
    def __init__(self, broker, request_id, actions, deployment_id):
        self.broker, self.request_id = broker, request_id
        self.actions = tuple(actions)
        self.target = Target(deployment_id=deployment_id)

    @property
    def connection_id(self):
        with self.broker._lock:
            pair = self.broker.grants.get(self.request_id)
            if pair is None:
                raise AccessDenied("Connection has no current approval")
            return pair.connection_id

    def __call__(self):
        with self.broker._lock:
            record = self.broker._records.get(self.request_id)
            grant = self.broker.grants.get(self.request_id)
            return (not self.broker._closed and record is not None and record.state == "approved"
                    and grant is not None and all(self.broker.authority.can(action,
                        target=self.target, connection_id=grant.connection_id, token=grant.token)
                        for action in self.actions))

    def commit(self, handoff=lambda: None):
        # This is the bounded local admission/queue boundary. Network I/O must
        # never hold the vault lock. An admitted read may finish after revoke,
        # but each subsequent lease check and result disclosure still denies.
        with self.broker._lock:
            if not self():
                raise AccessDenied("Connection approval ended")
            grant = self.broker.grants[self.request_id]
            with self.broker.authority._lock:
                for action in self.actions:
                    self.broker.authority.commit(action, lambda: None, target=self.target,
                        connection_id=grant.connection_id, token=grant.token,
                        request_id=uuid.uuid4().hex)
                return handoff()


class LiveConnectionBroker(TerminalConnectionBroker):
    """The legacy protocol is a presenter; the vault is the authority."""
    def __init__(self, vault, snapshot, handlers):
        self.vault, self.authority = vault, vault.access_control
        self.grants = {}
        super().__init__(snapshot, operation_handlers=handlers)

    def _public_status(self, record):
        result = super()._public_status(record)
        result["diagnostic_transport"] = "phoenix_session"
        result["workflow"] = "Use the permitted phoenix_terminal_connect before diagnostic reads. It binds the live swarm boot; if Connect is unavailable or fails, report the limit and stop. No SSH fallback."
        for resource in result["resources"]:
            resource["diagnostic_session_required"] = True
            resource["session_open_permitted"] = "sessions.open" in resource["operations"]
        return result

    def _expire_locked(self):
        super()._expire_locked()
        for request_id, record in self._records.items():
            if record.state != "approved":
                continue
            grant = self.grants.get(request_id)
            permissions = [Permission(action, Target(deployment_id=resource.deployment_id))
                           for resource in record.request.resources for action in resource.operations]
            if grant is None or not all(self.authority.can(p.action, target=p.target,
                    connection_id=grant.connection_id, token=grant.token) for p in permissions):
                record.state, record.reason, record.deadline = "revoked", "Live Phoenix approval ended", None
        for request_id, grant in tuple(self.grants.items()):
            record = self._records.get(request_id)
            if record is None or record.state != "approved":
                self.grants.pop(request_id, None)
                try:
                    self.authority.revoke_connection(grant.connection_id)
                except PermissionError:
                    pass

    def resolve(self, request_id, allowed, reason):
        # Qt owner thread only. No client method can reach this API.
        with self._lock:
            record = self._records.get(request_id)
            if self._closed or record is None or record.state != "pending":
                raise AccessDenied("Approval is no longer pending")
            connection_id = None
            if allowed:
                try:
                    if _binding(self.vault) != self.snapshot.vault_revision:
                        raise AccessDenied("Saved targets changed; reopen AI access")
                    permissions = [Permission(op, Target(deployment_id=r.deployment_id))
                                   for r in record.request.resources for op in r.operations]
                    connection_id = self.authority._enroll_transport(
                        record.request.client_label, record.secret_digest)
                    self.grants[request_id] = self.authority.approve(connection_id, permissions)
                except Exception:
                    if connection_id is not None:
                        self.authority.revoke_connection(connection_id)
                    super().resolve(request_id, False, "Phoenix could not grant or save this approval")
                    raise
            return super().resolve(request_id, allowed, reason)

    def _operation_lease(self, record, method, deployment_id):
        actions = ("agents.list", "logs.read") if method == "swarm.inspect" else (method,)
        lease = _Lease(self, record.request.request_id, actions, deployment_id)
        lease.commit()
        return lease

    def handle(self, method, params):
        if _binding(self.vault) != self.snapshot.vault_revision:
            raise AccessDenied("Phoenix targets or policy changed; reopen AI access")
        # The MCP identity must be a random secret, not a caller-selected weak
        # password. The existing Terminal client already generates 32 bytes.
        if method == "connection.request" and (not isinstance(params, dict)
                or not isinstance(params.get("client_secret"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", params["client_secret"])):
            raise AccessDenied("Invalid MCP client credential")
        value = super().handle(method, params)
        if method == "connection.disconnect":
            with self._lock:
                grant = self.grants.pop(params["request_id"], None)
                if grant is not None:
                    self.authority.revoke_connection(grant.connection_id)
        return value

    def guard_result(self, method, params, result):
        """Called immediately before the HTTP response is serialized."""
        if _binding(self.vault) != self.snapshot.vault_revision:
            raise AccessDenied("Phoenix targets or policy changed during the request")
        if method in SUPPORTED or method == "swarm.inspect":
            with self._lock:
                record = self._record_for(params["request_id"], params["client_secret"])
                self._operation_lease(record, method, params["deployment_id"]).commit()
                grant = self.grants[params["request_id"]]
                if method in {"swarms.list", "agents.list", "logs.read", "swarm.inspect", "sessions.open"}:
                    binding = result.get("session_binding")
                    if binding is None or not self.session_operations.current(
                            params["deployment_id"], grant.connection_id, binding):
                        raise AccessDenied("Live session or boot changed before result return")
        elif method in {"connection.status", "connection.request"}:
            # Do not disclose an old approved resource list after revocation.
            with self._lock:
                self._expire_locked()
                record = self._record_for(params["request_id"], params["client_secret"])
                result = self._public_status(record)
        return result

    def close(self):
        with self._lock:
            for grant in self.grants.values():
                try:
                    self.authority.revoke_connection(grant.connection_id)
                except PermissionError:
                    pass  # Vault lock already revoked every grant.
            self.grants.clear()
            super().close()


class _Sessions:
    """Typed Qt adapter. Deliberately never opens a credential-bearing child."""
    def __init__(self, runtime):
        self.runtime = runtime

    def handle(self, method, params):
        runtime, lease = self.runtime, params["lease"]
        if runtime.closed or _binding(runtime.vault) != runtime.broker.snapshot.vault_revision:
            raise AccessDenied("Phoenix targets changed before the view request")
        dep_id = params["deployment_id"]
        key = (lease.connection_id, dep_id)
        state = "available"
        if method == "diagnostic.stop":
            row = runtime.views.get(key)
            if row is not None and row[0] == params.get("session_id"):
                lease.commit(row[4].close)
            return {}
        if method in {"diagnostic.read", "diagnostic.session", "diagnostic.prepare"}:
            row = runtime.views.get(key)
            if row is None or row[4].closed:
                from phoenix_terminal.swarm_inspection import DiagnosticReadError
                raise DiagnosticReadError("Open a permitted live Phoenix AI session using phoenix_terminal_connect before reading diagnostics. No SSH fallback is used.")
            if method == "diagnostic.prepare":
                row[4].prepare_ingress(lease)
                return {}
            if method == "diagnostic.session":
                if not lease():
                    raise AccessDenied("Live session approval ended")
                return {"session": row[4]}
            ticket = row[4].submit(params["operation"], lease, params.get("agent_id"))
            return {"session": row[4], "ticket": ticket}
        def dispatch():
            nonlocal state
            if method == "sessions.open":
                if key in runtime.views and runtime.views[key][4].closed:
                    runtime.close_tab(runtime.views[key][1])
                if key in runtime.views:
                    state = "already_open"
                else:
                    if len(runtime.views) >= 32:
                        raise AccessDenied("AI inspection tab capacity reached")
                    tab = QWidget()
                    layout = QVBoxLayout(tab)
                    heading = QLabel("Live Phoenix AI session — read only. Waiting for a verified swarm boot; no native agent panel actions.")
                    heading.setTextFormat(Qt.TextFormat.PlainText)
                    heading.setWordWrap(True)
                    layout.addWidget(heading)
                    text = QPlainTextEdit()
                    text.setReadOnly(True)
                    text.setPlainText("Waiting for an approved inventory or inspection request from Gemma.")
                    layout.addWidget(text)
                    session_id = uuid.uuid4().hex
                    session = SessionDiagnostics(runtime.remote.targets[dep_id], session_id, lease, runtime)
                    try:
                        session.start()
                    except Exception:
                        session.close()
                        tab.deleteLater()
                        raise
                    runtime.views[key] = (session_id, tab, text, lease, session, heading)
                    label = next(r.label for r in runtime.broker.snapshot.resources if r.deployment_id == dep_id)
                    index = runtime.cockpit.tab_stack.addTab(tab, f"AI · {label}")
                    runtime.cockpit.tab_stack.setCurrentIndex(index)
                    state = "opened"
            runtime.update_count()
            return {"deployment_id": dep_id, "state": state, "session_kind": "ai_inspection",
                    "sessions": [{"session_id": row[0], "deployment_id": dep_id, "state": "view_observed"}]
                    if (row := runtime.views.get(key)) else []}
        return lease.commit(dispatch)


class LiveGateway(QObject):
    evidence_ready = pyqtSignal(object)

    def __init__(self, cockpit, vault, data_dir):
        super().__init__(cockpit)
        if not vault.access_control.ai_mode:
            raise AccessDenied("Reopen the vault in AI Mode first")
        if not str(data_dir).strip():
            raise ValueError("Select the Hermes client data directory")
        self.cockpit, self.vault = cockpit, vault
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.views, self.prompt = {}, None
        self._connecting, self._connect_lock = set(), threading.Lock()
        self.closed = False
        self.authority = vault.access_control
        policy = validate_policy(self.authority.policy(), deployment_ids(vault.read()))
        if not policy.enabled:
            raise AccessDenied("Enable and save the access_control policy first")
        for op in SUPPORTED:
            self.authority.register_action(op, target_fields=("deployment_id",))
        revision, data = _binding(vault), vault.read()
        resources, targets = [], {}
        try:
            for dep_id, item in public_inventory(data).items():
                ops = tuple(sorted(op for op in SUPPORTED if allows(policy, op, dep_id)))
                if not ops:
                    continue
                target = None
                if set(ops) & {"swarms.list", "agents.list", "logs.read"}:
                    target = live_target(data, dep_id)
                    targets[dep_id] = target
                elif "sessions.open" in ops:
                    target = live_target(data, dep_id)
                    targets[dep_id] = target
                resources.append(ApprovalResource(dep_id, item["deployment"].get("label") or dep_id,
                                                 ops, f"Live Phoenix session · {target.universe}" if target else ""))
        finally:
            data.clear()
        if not resources:
            raise AccessDenied("Select at least one deployment and supported operation")
        snapshot = TerminalSnapshot(vault.vault_path.stem, revision, tuple(resources),
                                    policy.approval_lifetime_seconds)
        self.remote = LiveSessionOperations(self, targets)
        self.dispatcher = QtBridgeDispatcher(_Sessions(self), timeout_seconds=5)
        self.dispatcher.setParent(self)
        handlers = {"swarms.list": self.remote.inventory, "agents.list": self.remote.agents,
                    "logs.read": self.remote.logs, "swarm.inspect": self.remote.inspect,
                    "sessions.list": self._sessions, "sessions.open": self._sessions}
        self.broker = LiveConnectionBroker(vault, snapshot, handlers)
        self.broker.session_operations = self.remote
        self.server = TerminalRequestServer(self._dispatch, self.data_dir)
        self.server._response_guard = self.broker.guard_result
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.evidence_ready.connect(self._show_evidence, Qt.ConnectionType.QueuedConnection)
        try:
            self.server.start()
        except Exception:
            self.broker.close()
            self.remote.close()
            raise
        self.timer.start(500)

    def _sessions(self, method, dep_id, identity, lease):
        if method != "sessions.open":
            return self.dispatcher.call(method, {"deployment_id": dep_id, "lease": lease})
        key = (lease.connection_id, dep_id)
        with self._connect_lock:
            if key in self._connecting:
                from phoenix_terminal.swarm_inspection import DiagnosticReadError
                raise DiagnosticReadError("Connect is already in progress for this client and deployment; wait for its result, then stop if it fails.")
            self._connecting.add(key)
        try:
            return self._connect_session(method, dep_id, lease)
        finally:
            with self._connect_lock:
                self._connecting.discard(key)

    def connect_in_progress(self, connection_id, deployment_id):
        with self._connect_lock:
            return (connection_id, deployment_id) in self._connecting

    def _connect_session(self, method, dep_id, lease):
        result = self.dispatcher.call(method, {"deployment_id": dep_id, "lease": lease})
        if method == "sessions.open":
            try:
                session = self.remote.bind(dep_id, lease, connect=True)
                result["session_binding"] = session.binding()
                result["connection_readiness"] = session.readiness()
                self.evidence_ready.emit((lease, dep_id, {
                    "status": "HTTPS accepted the read-only handshake and its signed WebSocket reply verified the swarm boot; ready for diagnostics.",
                    "session_binding": result["session_binding"],
                    "connection_readiness": result["connection_readiness"],
                }))
            except Exception as error:
                # Publish the failure before closing the session's connectors.
                # AI sessions have no background reconnect monitor.
                self.evidence_ready.emit((lease, dep_id, {"status": "Connection readiness failed; no diagnostics were disclosed.",
                    "connection_readiness": {"state": "failed", "attempts": getattr(error, "attempts", 0),
                        "max_attempts": 3, "timeout_seconds": 50,
                        "last_error_code": getattr(error, "code", "CONNECT_FAILED")}}))
                rows = result.get("sessions", [])
                if rows:
                    try:
                        self.dispatcher.call("diagnostic.stop", {"deployment_id": dep_id,
                            "lease": lease, "session_id": rows[0]["session_id"]})
                    except (PermissionError, RuntimeError, TimeoutError):
                        pass  # Revocation/lock cleanup owns an ended lease.
                raise
        return result

    def _dispatch(self, method, params):
        result = self.broker.handle(method, params)
        if method in {"swarms.list", "agents.list", "logs.read", "swarm.inspect"}:
            with self.broker._lock:
                record = self.broker._record_for(params["request_id"], params["client_secret"])
                lease = self.broker._operation_lease(record, method, params["deployment_id"])
            self.evidence_ready.emit((lease, params["deployment_id"], deepcopy(result)))
        return result

    def _show_evidence(self, event):
        try:
            lease, dep_id, result = event
            if (self.closed or not lease()
                    or _binding(self.vault) != self.broker.snapshot.vault_revision):
                return
            row = self.views.get((lease.connection_id, dep_id))
            if row:
                binding = result.get("session_binding")
                if binding is not None and not row[4].current(binding):
                    return
                def display():
                    if binding is not None:
                        row[5].setText("Live Phoenix AI session — read only. "
                            f"Verified swarm boot: {binding['runtime_id']}; no native agent panel actions.")
                    elif result.get("connection_readiness", {}).get("state") in {"waiting", "retrying"}:
                        ready = result["connection_readiness"]
                        row[5].setText("Live Phoenix AI session — read only. "
                            f"Connecting: {ready['stage']} (attempt {ready['attempts']}/{ready['max_attempts']}).")
                    else:
                        row[5].setText("Live Phoenix AI session — read only. "
                            "Diagnostic boot binding unavailable; no verified diagnostic evidence received.")
                    row[2].setPlainText(json.dumps(result, indent=2, ensure_ascii=False))
                lease.commit(display)
        except (PermissionError, RuntimeError):
            pass  # A queued result can expire before Qt consumes it.

    def _refresh(self):
        if self.closed:
            return
        try:
            if (not self.authority.accepting_connections
                    or _binding(self.vault) != self.broker.snapshot.vault_revision):
                self.stop()
                return
            counts = self.broker.counts()  # Synchronize central revocation/expiry.
            self.cockpit.control_panel.terminal_btn.setText(f"AI Mode · {counts['active']} connected")
            for key, row in tuple(self.views.items()):
                if not row[3]() or row[4].closed:
                    self.close_tab(row[1])
            if self.prompt is None:
                request = self.broker.next_approval()
                if request:
                    from phoenix_terminal.connection_approval_dialog import ConnectionApprovalDialog
                    self.prompt = ConnectionApprovalDialog(request, self.cockpit)
                    self.prompt.setWindowTitle("Allow Phoenix AI connection?")
                    self.prompt.finished.connect(lambda _: self._decide(request.request_id))
                    self.prompt.open()
                    self.prompt.summon()
        except Exception:
            self.stop()

    def _decide(self, request_id):
        prompt, self.prompt = self.prompt, None
        if prompt is None:
            return
        try:
            if not self.closed:
                self.broker.resolve(request_id, prompt.allowed, prompt.decision_reason)
        except Exception as exc:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self.cockpit, "AI approval denied", str(exc))
        finally:
            prompt.deleteLater()

    def update_count(self):
        self.cockpit.status_sessions.setText(f"Sessions: {len(self.cockpit._active_sessions) + len(self.views)}")

    def close_tab(self, tab):
        for key, row in tuple(self.views.items()):
            if row[1] is tab:
                row[4].close()
                row[2].clear()
                index = self.cockpit.tab_stack.indexOf(tab)
                if index >= 0:
                    self.cockpit.tab_stack.removeTab(index)
                tab.deleteLater()
                self.views.pop(key)
                self.update_count()
                return True
        return False

    def stop(self):
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        self.broker.close()  # Revoke first; transport teardown may take time.
        self.remote.close()
        if self.prompt is not None:
            self.prompt.reject()
        for row in tuple(self.views.values()):
            self.close_tab(row[1])
        self.server.stop()
        self.cockpit.control_panel.terminal_btn.setText("AI Mode · Access closed")
