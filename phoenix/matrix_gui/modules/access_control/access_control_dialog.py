"""Operator UI. Administrative methods never appear in the MCP catalog."""
import os
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QInputDialog)

from matrix_gui.core.event_bus import EventBus
from matrix_gui.core.panel.home.terminal_access_controls import TerminalAccessControls
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton


class AccessControlDialog(QDialog):
    def __init__(self, cockpit):
        super().__init__(cockpit)
        self.cockpit, self.vault = cockpit, VaultCoreSingleton.get()
        self.authority = self.vault.access_control
        self.setWindowTitle("Phoenix AI Mode — Access control")
        self.resize(1080, 740)
        layout = QVBoxLayout(self)
        notice = QLabel("AI Mode" if self.authority.ai_mode else
                        "Normal Mode — configure here, then close and reopen the vault in AI Mode.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        policy_page = QWidget()
        policy_layout = QVBoxLayout(policy_page)
        self.controls = TerminalAccessControls(policy_page, vault_authority=self.vault,
                                               terminal_mode=True, access_mode=True)
        policy_layout.addWidget(self.controls)
        import_button = QPushButton("Load prior Terminal selections for review")
        import_button.clicked.connect(self._load_prior)
        policy_layout.addWidget(import_button)
        tabs.addTab(policy_page, "Policy")

        live_page = QWidget()
        live_layout = QVBoxLayout(live_page)
        guidance = QLabel("Use the same client data directory configured in Hermes. Close the separate Terminal console first. Phoenix presents each approval request here; closing this settings window keeps AI access open.")
        guidance.setWordWrap(True)
        live_layout.addWidget(guidance)
        default_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PhoenixTerminal"
        self.directory = QLineEdit(os.environ.get("PHOENIX_TERMINAL_DATA_DIR", str(default_dir)))
        self.directory.setPlaceholderText("Hermes Phoenix Terminal client data directory")
        live_layout.addWidget(self.directory)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        live_layout.addWidget(self.status)
        row = QHBoxLayout()
        self.open_button = QPushButton("Open AI access")
        self.open_button.clicked.connect(self._open)
        self.stop_button = QPushButton("Close AI connections")
        self.stop_button.clicked.connect(self._stop)
        kill = QPushButton("KILL AI ACCESS — until next unlock")
        kill.setStyleSheet("color: #ff7060; font-weight: bold;")
        kill.clicked.connect(self._kill)
        for button in (self.open_button, self.stop_button, kill):
            row.addWidget(button)
        live_layout.addLayout(row)
        self.connections = QTreeWidget()
        self.connections.setHeaderLabels(("Client", "Connection ID", "Expires", "Approvals", "Committed calls"))
        live_layout.addWidget(self.connections)
        revoke_connection = QPushButton("Revoke selected connection")
        revoke_connection.clicked.connect(self._revoke_connection)
        live_layout.addWidget(revoke_connection)
        tabs.addTab(live_page, "Connections / Kill switch")

        credentials_page = QWidget()
        credentials_layout = QVBoxLayout(credentials_page)
        description = QLabel("Approved MCP clients are enrolled here by their secret verifier. They use the one shared policy. Revoking a credential blocks every connection using that identity, including requests to enroll it again.")
        description.setWordWrap(True)
        credentials_layout.addWidget(description)
        self.credentials = QTreeWidget()
        self.credentials.setHeaderLabels(("Client", "Credential ID", "Created", "Revoked"))
        credentials_layout.addWidget(self.credentials)
        create_credential = QPushButton("Create client identity in the selected data directory…")
        create_credential.clicked.connect(self._create_credential)
        credentials_layout.addWidget(create_credential)
        revoke_credential = QPushButton("Revoke selected credential")
        revoke_credential.clicked.connect(self._revoke_credential)
        credentials_layout.addWidget(revoke_credential)
        tabs.addTab(credentials_page, "Credentials")

        coverage = QLabel(
            "Enabled adapters: live Phoenix read-only sessions, agent tree, process/thread/spawn observations, work progress, recent logs and combined inspection. Reads use the saved WSS/HTTPS connectors; no SSH fallback. Updated Matrix, Log Streamer and core diagnostic code are required on the server.\n\n"
            "Gateway checks: MCP ingress → current vault policy and targets → operator-approved signed grant → bounded read admission → verified callback sender and request/session/boot binding → lease check before result disclosure → Qt view update.\n\n"
            "Blocked in AI Mode: ordinary Connect subprocesses, Deploy, Registry edits, Swarms stop, Railgun operations, dynamic agent commands, custom panels and legacy session IPC. These require explicit typed adapters before they can be enabled.\n\n"
            "Kill switch revokes first, closes AI tabs and prevents new operations. Already admitted remote reads or HTTP responses may finish; revocation cannot undo committed work. Evidence is sampled and is never release approval.\n\n"
            "AI Mode governs this application. It is not an OS sandbox against a model with independent shell or filesystem access under your Windows account."
        )
        coverage.setWordWrap(True)
        coverage.setTextFormat(Qt.TextFormat.PlainText)
        tabs.addTab(coverage, "Gateways / Coverage")
        close = QPushButton("Close settings")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._safe_refresh)
        self.timer.start(750)
        EventBus.on("vault.closed", self._vault_closed)
        self._refresh()

    def _runtime(self):
        return getattr(self.cockpit, "_ai_gateway", None)

    def _safe_refresh(self):
        try:
            self._refresh()
        except Exception:
            self.timer.stop()
            self._stop_without_refresh()
            self.status.setText("Access control could not read the vault. AI connections closed; reopen the vault.")

    def _stop_without_refresh(self):
        if self._runtime():
            self._runtime().stop()

    def _open(self):
        try:
            if not self.authority.ai_mode:
                raise PermissionError("Close the vault, then select AI Mode at the top of the unlock options")
            if self._runtime() and not self._runtime().closed:
                return
            from .live_gateway import LiveGateway
            self.cockpit._ai_gateway = LiveGateway(self.cockpit, self.vault, self.directory.text())
            self._refresh()
        except Exception as exc:
            QMessageBox.warning(self, "AI access could not open", str(exc))

    def _stop(self):
        self._stop_without_refresh()
        self._refresh()

    def _kill(self):
        self.authority.kill_switch()
        self._stop()
        self.status.setText("AI access killed. Close and unlock the vault again before allowing another connection.")

    def _revoke_connection(self):
        selected = self.connections.currentItem()
        if selected:
            self.authority.revoke_connection(selected.text(1))
            self._refresh()

    def _revoke_credential(self):
        selected = self.credentials.currentItem()
        if selected:
            try:
                self.authority.revoke_credential(selected.text(1))
            except Exception as exc:
                QMessageBox.warning(self, "Credential revocation", str(exc))
            self._refresh()

    def _create_credential(self):
        label, accepted = QInputDialog.getText(self, "Create AI client identity", "Client label:")
        if not accepted:
            return
        credential = None
        try:
            from .live_gateway import _load_terminal
            _load_terminal()
            from phoenix_terminal.terminal_client import TerminalClientIdentity
            import secrets
            if not self.directory.text().strip():
                raise ValueError("Select the Hermes client data directory first")
            identity = TerminalClientIdentity(Path(self.directory.text()).expanduser().resolve())
            if identity.path.exists():
                raise ValueError("A client identity already exists here. Use its approval request to enroll it, or select a separate client data directory.")
            credential = self.authority.create_credential(label)
            identity._write({"request_id": secrets.token_urlsafe(18), "client_label": label.strip(),
                             "client_secret": credential.secret})
            QMessageBox.information(self, "Client identity created", "The secret was written to the client's private identity file. It was not displayed or copied. Configure Hermes with this same data directory, then request approval.")
        except Exception as exc:
            if credential is not None:
                try:
                    self.authority.revoke_credential(credential.credential_id)
                except Exception:
                    pass
            QMessageBox.warning(self, "Identity was not created", str(exc))
        self._refresh()

    def _load_prior(self):
        # Preview only. No migration, permission grant or listener activation.
        from matrix_gui.modules.vault.terminal_access_policy import validate_policy, deployment_ids
        try:
            data = self.vault.read()
            policy = validate_policy(data.get("terminal_access"), deployment_ids(data))
            self.controls.enabled_checkbox.setChecked(policy.enabled)
            self.controls.lifetime_seconds.setValue(policy.approval_lifetime_seconds)
            for action, checkbox in self.controls.operation_checkboxes.items():
                supported = self.controls.supports_operation(action)
                rule = policy.permissions[action]
                checkbox.setChecked(rule.enabled and supported)
                for index in range(self.controls.deployment_scope.topLevelItemCount()):
                    item = self.controls.deployment_scope.topLevelItem(index)
                    selected = supported and item.data(0, Qt.ItemDataRole.UserRole) in rule.deployment_ids
                    self.controls.set_deployment_selection(item, action, selected)
            self.controls.summary.setText("Prior Terminal selections loaded for review. Save AI access policy to apply them.")
        except Exception as exc:
            QMessageBox.warning(self, "Could not load prior selections", str(exc))

    def _refresh(self):
        if self.vault._closed:
            self.reject()
            return
        runtime = self._runtime()
        active = runtime is not None and not runtime.closed
        self.directory.setEnabled(not active)
        self.open_button.setEnabled(self.authority.accepting_connections and not active)
        self.stop_button.setEnabled(active)
        counts = runtime.broker.counts() if active else {"pending": 0, "active": 0}
        state = "AI access open" if active else ("AI access killed until next unlock"
            if self.authority.ai_mode and not self.authority.accepting_connections else "AI access closed")
        self.status.setText(f"{state} · Pending: {counts['pending']} · Approved: {counts['active']}")
        selected_connection = self.connections.currentItem()
        identifier = selected_connection.text(1) if selected_connection else None
        self.connections.clear()
        for item in self.authority.list_connections():
            row = QTreeWidgetItem((item["label"], item["connection_id"], item["expires_at"],
                                   str(item["approvals"]), str(item["committed_requests"])))
            self.connections.addTopLevelItem(row)
            if row.text(1) == identifier:
                self.connections.setCurrentItem(row)
        selected_credential = self.credentials.currentItem()
        identifier = selected_credential.text(1) if selected_credential else None
        self.credentials.clear()
        for item in self.authority.list_credentials():
            row = QTreeWidgetItem((item["label"], item["credential_id"], item["created_at"],
                item["revoked_at"] or ("disabled this unlock" if item["disabled_this_unlock"] else "active")))
            self.credentials.addTopLevelItem(row)
            if row.text(1) == identifier:
                self.credentials.setCurrentItem(row)

    def _vault_closed(self, **_):
        self.reject()

    def done(self, result):
        self.timer.stop()
        EventBus.off("vault.closed", self._vault_closed)
        super().done(result)
