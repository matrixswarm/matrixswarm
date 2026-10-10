"""Independent operator runtime for approved, fixed-target live alert reads."""

from __future__ import annotations

import getpass
import importlib
import os
from pathlib import Path
import sys
import warnings

from .connection_approval import ApprovalResource, CURRENT_OPERATIONS
from .connection_approval_dialog import ConnectionApprovalDialog
from .connection_broker import TerminalConnectionBroker, TerminalSnapshot
from .terminal_server import TerminalRequestServer
from .vault_console import load_vault_data, public_inventory


def build_snapshot(phoenix_root, vault_path, password, *, supported_operations=()):
    """Create an immutable, credential-free approval snapshot."""
    return _prepare_toolkit(phoenix_root, vault_path, password, supported_operations)[0]


def load_live_toolkit(phoenix_root, vault_path, password):
    """Decrypt once; bind public approval and private fixed targets to that revision."""
    return _prepare_toolkit(phoenix_root, vault_path, password, CURRENT_OPERATIONS, live=True)


class ToolkitTargets(dict):
    """Alert targets plus private SSH targets; never serialized to clients."""
    def __init__(self):
        super().__init__()
        self.remote_targets = {}


def _prepare_toolkit(phoenix_root, vault_path, password, supported_operations, *, live=False):
    root = Path(phoenix_root).resolve()
    data = load_vault_data(root, vault_path, password)
    try:
        sys.path.insert(0, str(root))
        policy_module = importlib.import_module(
            "matrix_gui.modules.vault.terminal_access_policy"
        )
        expected_policy = (
            root / "matrix_gui/modules/vault/terminal_access_policy.py"
        ).resolve()
        if Path(policy_module.__file__).resolve() != expected_policy:
            raise RuntimeError(
                "A different Phoenix policy module is already loaded. "
                "Start a fresh terminal process."
            )
        policy = policy_module.policy_from_vault(data)
        if not policy.enabled:
            raise ValueError(
                "Terminal access is disabled in this Vault. Enable and save it "
                "from the Terminal Mode window in Phoenix."
            )
        revision = policy_module.vault_revision(data)
        inventory = public_inventory(data)
        supported = frozenset(supported_operations)
        if supported.difference(CURRENT_OPERATIONS):
            raise ValueError("Terminal runtime declared an unsupported operation adapter")
        resources = []
        targets = ToolkitTargets()
        for deployment_id, item in inventory.items():
            deployment = item["deployment"]
            label = deployment.get("label") or deployment_id
            operations = tuple(sorted(op for op in supported
                if policy_module.allows(policy, op, deployment_id)))
            destination = ""
            if set(operations).intersection({"swarms.list", "railgun.launch", "agents.list", "logs.read"}):
                from .remote_access import target_from_vault
                target = target_from_vault(data, deployment_id, revision,
                    launch="railgun.launch" in operations,
                    diagnostics="agents.list" in operations, logs="logs.read" in operations)
                for module_name, relative in (
                    ("matrix_gui.modules.railgun.ssh_support", "matrix_gui/modules/railgun/ssh_support.py"),
                    ("matrix_gui.modules.railgun.remote_shell", "matrix_gui/modules/railgun/remote_shell.py"),
                ):
                    if Path(sys.modules[module_name].__file__).resolve() != (root / relative).resolve():
                        raise RuntimeError("A different Phoenix SSH module is loaded; start a fresh Terminal")
                destination = target.destination
                if live:
                    targets.remote_targets[deployment_id] = target
            resources.append(ApprovalResource(deployment_id, label, operations, destination))
        if not resources:
            raise ValueError("Terminal access requires at least one prepared deployment")
        snapshot = TerminalSnapshot(
            vault_label=Path(vault_path).stem,
            vault_revision=revision,
            resources=tuple(resources),
            approval_lifetime_seconds=policy.approval_lifetime_seconds,
        )
        if live:
            from .live_alerts import MAX_FEEDS, target_from_deployment
            permitted = [r for r in resources if "alerts.read" in r.operations]
            if len(permitted) > MAX_FEEDS:
                raise ValueError(f"At most {MAX_FEEDS} alert feeds may be enabled")
            for resource in permitted:
                try:
                    targets[resource.deployment_id] = target_from_deployment(
                        resource.deployment_id, data["deployments"][resource.deployment_id])
                except ValueError as exc:
                    raise ValueError(f"Deployment {resource.deployment_id}: {exc}") from None
        return snapshot, targets
    finally:
        data.clear()
        if sys.path and sys.path[0] == str(root):
            sys.path.pop(0)


def _require_private_password_prompt():
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ValueError(
            "Terminal Vault opening requires a private interactive terminal; "
            "piped credentials are refused."
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass("Phoenix vault password (operator only): ")
    except getpass.GetPassWarning:
        raise RuntimeError(
            "Hidden password entry is unavailable; Vault was not opened."
        ) from None


def _require_desktop():
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        raise RuntimeError(
            "Terminal connection approval requires a desktop display. "
            "Headless auto-approval is forbidden."
        )


def run_terminal(phoenix_root, vault_path, data_dir, *, alert_reader=None):
    """Open the Vault privately and run the Terminal-owned approval window."""
    _require_desktop()
    password = _require_private_password_prompt()
    try:
        if alert_reader is None:
            snapshot, targets = load_live_toolkit(phoenix_root, vault_path, password)
        else:
            snapshot = build_snapshot(phoenix_root, vault_path, password,
                                      supported_operations=("alerts.read",))
    finally:
        password = None

    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtWidgets import (
        QApplication,
        QLabel,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    app = QApplication.instance() or QApplication(sys.argv[:1])
    feeds = None
    remote = None
    if alert_reader is None:
        from .live_alerts import LiveAlertFeeds
        feeds = LiveAlertFeeds(targets)
        from .remote_access import RemoteOperations
        remote = RemoteOperations(getattr(targets, "remote_targets", {}))
        if hasattr(targets, "remote_targets"):
            targets.remote_targets.clear()
        targets.clear()
        alert_reader = feeds.read
    handlers = {"alerts.read": alert_reader}
    if remote is not None:
        handlers.update({"swarms.list": remote.inventory, "railgun.launch": remote.launch,
                         "railgun.status": remote.status, "agents.list": remote.agents,
                         "logs.read": remote.logs, "swarm.inspect": remote.inspect})
    from .cockpit_sessions import CockpitSessionClient
    cockpit = CockpitSessionClient(data_dir)
    handlers.update({"sessions.list": cockpit.call, "sessions.open": cockpit.call})
    broker = TerminalConnectionBroker(snapshot, operation_handlers=handlers)
    server = TerminalRequestServer(broker.handle, Path(data_dir))
    active_dialog = {"value": None}

    class TerminalWindow(QWidget):
        def closeEvent(self, event):
            broker.close()
            if active_dialog["value"] is not None:
                active_dialog["value"].reject()
            super().closeEvent(event)

    window = TerminalWindow()
    window.setWindowTitle("Phoenix Terminal — Terminal access")
    window.resize(560, 260)
    layout = QVBoxLayout(window)
    heading = QLabel("Terminal access is open")
    heading.setStyleSheet("font-size: 18px; font-weight: 700;")
    layout.addWidget(heading)
    detail = QLabel(
        f"Toolkit: {snapshot.vault_label}\n"
        f"Vault revision: {snapshot.vault_revision[:12]}…\n"
        f"Prepared deployments: {len(snapshot.resources)}\n\n"
        "Clients receive nothing until you approve their connection. "
        "Only permitted live swarm alerts are connected after approval. "
        "Agent inventory, recent logs and Swarms reads use fixed saved servers. "
        "Cockpit session access uses the separately running Phoenix window. "
        "Railgun launches are separate and inactive-only. "
        "No replacement, arbitrary commands, edits, or credential export."
    )
    detail.setTextFormat(Qt.TextFormat.PlainText)
    detail.setWordWrap(True)
    layout.addWidget(detail)
    client_path = QLabel(f"Client data directory: {Path(data_dir).resolve()}")
    client_path.setTextFormat(Qt.TextFormat.PlainText)
    client_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    client_path.setWordWrap(True)
    layout.addWidget(client_path)
    copy_setup = QPushButton("Copy client setup (PowerShell)" if os.name == "nt" else "Copy client setup (shell)")
    def copy_client_setup():
        from .client_setup import client_instructions
        QApplication.clipboard().setText(client_instructions(data_dir))
        copy_setup.setText("Client setup copied")
    copy_setup.clicked.connect(copy_client_setup)
    layout.addWidget(copy_setup)
    status = QLabel("Pending requests: 0 · Active connections: 0")
    status.setTextFormat(Qt.TextFormat.PlainText)
    layout.addWidget(status)
    feed_status = QLabel("Alert feeds: waiting for operator approval")
    feed_status.setTextFormat(Qt.TextFormat.PlainText)
    feed_status.setWordWrap(True)
    layout.addWidget(feed_status)
    launch_status = QLabel("Railgun: no launch requests")
    launch_status.setTextFormat(Qt.TextFormat.PlainText)
    launch_status.setWordWrap(True)
    layout.addWidget(launch_status)
    read_hint = QLabel(
        "Read received messages in the client console: terminal alerts DEPLOYMENT_ID. "
        "terminal request/status reports approval only, not the alert buffer. "
        "Rejected packets do not erase alerts already received. "
        "UNEXPECTED_SENDER means the packet did not match the saved alert receiver. "
        "SSH inventory and log inspection have separate results."
    )
    read_hint.setWordWrap(True)
    layout.addWidget(read_hint)
    close_button = QPushButton("Lock Terminal access and exit")
    close_button.clicked.connect(window.close)
    layout.addWidget(close_button)

    def refresh():
        counts = broker.counts()
        status.setText(
            f"Pending requests: {counts['pending']} · Active connections: {counts['active']}"
        )
        if remote is not None:
            jobs = remote.operator_statuses()
            launch_status.setText("\n".join(
                f"Railgun {j['deployment_id']} · {j['operation_id'][:12]}: {j['state']}"
                + (" — operator reconciliation required" if j['operator_reconciliation_required'] else "")
                for j in jobs[-4:]
            ) + (f"\n{len(jobs) - 4} earlier job(s); receipts remain on server." if len(jobs) > 4 else "")
                if jobs else "Railgun: no launch requests")
        if feeds is not None:
            states = feeds.statuses()
            feed_status.setText("\n".join(
                f"Alert feed {key}: {value['state']} — {value['code']}\n"
                f"Received alerts: {value['received_alerts']} · Rejected packets: {value['rejected_packets']}"
                + (f" · Last rejection: {value['last_rejection']}" if value['last_rejection'] else "")
                for key, value in states.items()
            ) or "Alert feeds: no active approved connection")
        if active_dialog["value"] is not None:
            return
        request = broker.next_approval()
        if request is None:
            return
        dialog = ConnectionApprovalDialog(request, window)
        active_dialog["value"] = dialog
        try:
            status.setText(
                "Approval required — check the Terminal connection dialog"
            )
            status.setStyleSheet("color: #ffb347; font-weight: 700;")
            window.showNormal()
            window.raise_()
            window.activateWindow()
            QApplication.alert(window, 0)
            app.processEvents()
            dialog.summon()
            dialog.exec()
            try:
                broker.resolve(request.request_id, dialog.allowed, dialog.decision_reason)
            except PermissionError:
                # Lock/disconnect won the race; never revive the request.
                pass
        finally:
            active_dialog["value"] = None
            status.setStyleSheet("")
            counts = broker.counts()
            status.setText(
                f"Pending requests: {counts['pending']} · "
                f"Active connections: {counts['active']}"
            )
            dialog.deleteLater()

    timer = QTimer(window)
    timer.setInterval(250)
    timer.timeout.connect(refresh)
    try:
        server.start()
        if feeds is not None:
            feeds.start(broker.active_alert_grants)
        timer.start()
        window.show()
        print(
            "Phoenix Terminal access is open. Awaiting client requests; "
            "permitted live alert feeds start only after operator approval."
        )
        return app.exec()
    finally:
        timer.stop()
        broker.close()
        if remote is not None:
            remote.close()
        if feeds is not None:
            feeds.close()
        dialog = active_dialog["value"]
        if dialog is not None:
            dialog.reject()
        server.stop()
        window.deleteLater()
