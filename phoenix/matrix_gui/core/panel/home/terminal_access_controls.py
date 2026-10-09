"""Terminal Mode authoring controls for the persisted Terminal access policy."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.modules.vault.terminal_access_policy import (
    DEFAULT_APPROVAL_LIFETIME_SECONDS,
    MAX_APPROVAL_LIFETIME_SECONDS,
    MIN_APPROVAL_LIFETIME_SECONDS,
    SECTION_KEY,
    TerminalAccessPolicyError,
    default_policy,
    deployment_ids,
    validate_policy,
)


class TerminalAccessControls(QGroupBox):
    """Author policy only; this widget never starts or approves a connection."""

    _AI_UNAVAILABLE_OPERATIONS = {
        "alerts.read": (
            "Pending",
            "Live alert subscriptions have no approved adapter yet. Alert permission "
            "cannot be selected or saved in this pilot. Logs / inspect can still "
            "report findings from recent logs.",
        ),
        "railgun.launch": (
            "Blocked",
            "Railgun launch has no approved AI adapter in this pilot. Launch "
            "permission cannot be selected or saved.",
        ),
    }

    def __init__(self, parent=None, *, vault_authority=None, terminal_mode=False, access_mode=False):
        super().__init__("AI access" if access_mode else "Terminal access", parent)
        self.setObjectName("TerminalAccessControls")
        self._vault_authority = vault_authority
        self._terminal_mode = terminal_mode is True
        self._access_mode = access_mode is True
        self._loading = False

        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Prepare the exact authority Phoenix Terminal may request. "
            "Saving this policy does not start a listener or approve a client."
        )
        explanation.setWordWrap(True)
        explanation.setTextFormat(Qt.TextFormat.PlainText)
        explanation.setObjectName("TerminalAccessExplanation")
        layout.addWidget(explanation)

        self.enabled_checkbox = QCheckBox("Allow Terminal access requests for this Vault")
        self.enabled_checkbox.setObjectName("TerminalAccessEnabled")
        self.enabled_checkbox.toggled.connect(self._sync_enabled_state)
        layout.addWidget(self.enabled_checkbox)

        lifetime_row = QHBoxLayout()
        lifetime_row.addWidget(QLabel("Maximum approved connection lifetime:"))
        self.lifetime_seconds = QSpinBox()
        self.lifetime_seconds.setObjectName("TerminalAccessLifetime")
        self.lifetime_seconds.setRange(
            MIN_APPROVAL_LIFETIME_SECONDS,
            MAX_APPROVAL_LIFETIME_SECONDS,
        )
        self.lifetime_seconds.setSingleStep(60)
        self.lifetime_seconds.setSuffix(" seconds")
        self.lifetime_seconds.setValue(DEFAULT_APPROVAL_LIFETIME_SECONDS)
        self.lifetime_seconds.valueChanged.connect(lambda *_: self._sync_enabled_state())
        lifetime_row.addWidget(self.lifetime_seconds)
        lifetime_row.addStretch()
        layout.addLayout(lifetime_row)

        self.alerts_checkbox = QCheckBox("Prepare read-only swarm alert permission")
        self.alerts_checkbox.setObjectName("TerminalAlertsReadEnabled")
        self.alerts_checkbox.setToolTip(
            "Read only. This does not permit acknowledge, delete, mute, restart, "
            "settings, or any other action."
        )
        self.alerts_checkbox.toggled.connect(self._sync_enabled_state)
        layout.addWidget(self.alerts_checkbox)

        self.swarms_checkbox = QCheckBox("Prepare read-only Swarms inventory on saved servers")
        self.railgun_checkbox = QCheckBox("Prepare Railgun launch of saved deployments (never replace active swarms)")
        self.agents_checkbox = QCheckBox("Prepare read-only agent process and heartbeat inventory")
        self.logs_checkbox = QCheckBox("Prepare read-only recent agent logs (swarm inspection also requires agent inventory above)")
        self.sessions_checkbox = QCheckBox("Prepare listing of Phoenix cockpit session tabs")
        self.connect_checkbox = QCheckBox("Prepare opening a Phoenix cockpit session (Connect; does not start a swarm)")
        self.operation_checkboxes = {
            "alerts.read": self.alerts_checkbox,
            "swarms.list": self.swarms_checkbox,
            "agents.list": self.agents_checkbox,
            "logs.read": self.logs_checkbox,
            "sessions.list": self.sessions_checkbox,
            "sessions.open": self.connect_checkbox,
            "railgun.launch": self.railgun_checkbox,
        }
        for operation, checkbox in tuple(self.operation_checkboxes.items())[1:]:
            checkbox.setObjectName("Terminal" + operation.replace(".", "_") + "Enabled")
            checkbox.setToolTip("Exact saved deployment only. Logs may contain sensitive application text; review before sharing with a model. No arbitrary shell, edit, kill, or restart authority.")
            checkbox.toggled.connect(self._sync_enabled_state)
            layout.addWidget(checkbox)

        self.deployment_scope = QTreeWidget()
        self.deployment_scope.setObjectName("TerminalAlertDeploymentScope")
        self._destination_column = len(self.operation_checkboxes) + 1
        self.deployment_scope.setHeaderLabels(("Prepared deployment", "Alert reads", "Swarms inventory", "Agents", "Logs / inspect", "Session list", "Connect", "Railgun launch", "Fixed destination"))
        header = self.deployment_scope.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, self._destination_column):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self._destination_column, QHeaderView.ResizeMode.Stretch)
        self.deployment_scope.setStyleSheet(
            "QHeaderView { border: none; margin: 0; padding: 0; }"
            "QHeaderView::section { background: #1b1b1d; color: #ddd; "
            "border: 1px solid #333; padding: 6px; }"
        )
        self.deployment_scope.setRootIsDecorated(False)
        self.deployment_scope.setMinimumHeight(100)
        self.deployment_scope.setMaximumHeight(180)
        self.deployment_scope.itemChanged.connect(lambda *_: self._sync_enabled_state())
        layout.addWidget(self.deployment_scope)

        row = QHBoxLayout()
        self.summary = QLabel("Terminal access is off.")
        self.summary.setObjectName("TerminalAccessSummary")
        self.summary.setWordWrap(True)
        self.save_button = QPushButton("Save Terminal access policy")
        self.save_button.setObjectName("SaveTerminalAccessPolicy")
        self.save_button.clicked.connect(self.save_policy)
        row.addWidget(self.summary, stretch=1)
        row.addWidget(self.save_button)
        layout.addLayout(row)

        self.refresh_from_vault()
        if self._access_mode:
            explanation.setText("Choose what an AI connection may request. Live diagnostic reads require Connect for the same deployment. Saving revokes current approvals; open AI access separately and approve the requesting client in Phoenix.")
            self.enabled_checkbox.setText("Allow AI access requests for this Vault")
            self.connect_checkbox.setText("Prepare opening a live read-only Phoenix AI session (does not boot a swarm)")
            self.swarms_checkbox.setText("Prepare read-only inventory of the connected live swarm")
            self.agents_checkbox.setText("Prepare live agent tree, process/thread/spawn and work observations")
            self.logs_checkbox.setText("Prepare current-boot recent logs (inspection also requires agent inventory)")
            self.sessions_checkbox.setText("Prepare listing the client's AI inspection tabs")
            self.alerts_checkbox.setText("Live alert subscription — adapter pending")
            self.railgun_checkbox.setText("Railgun launch — blocked in this AI Mode pilot")
            for operation, (_, tooltip) in self._AI_UNAVAILABLE_OPERATIONS.items():
                self.operation_checkboxes[operation].setToolTip(tooltip)
            self.save_button.setText("Save AI access policy")
            self._sync_enabled_state()

    def _authority(self):
        return self._vault_authority or VaultCoreSingleton.get()

    def refresh_from_vault(self):
        self.setVisible(self._terminal_mode)
        if not self._terminal_mode:
            return
        self._loading = True
        try:
            vault = self._authority().read()
            self.setEnabled(True)
            ids = deployment_ids(vault)
            try:
                raw_policy = self._authority().access_control.policy() if self._access_mode else vault.get(SECTION_KEY)
                policy = validate_policy(raw_policy, ids)
                warning = ""
            except TerminalAccessPolicyError as exc:
                policy = default_policy()
                warning = f"Stored policy is invalid and grants nothing: {exc}"

            self.enabled_checkbox.setChecked(policy.enabled)
            self.lifetime_seconds.setValue(policy.approval_lifetime_seconds)
            for operation, checkbox in self.operation_checkboxes.items():
                checkbox.setChecked(policy.permissions[operation].enabled)
            deployments = vault.get("deployments", {})
            self.deployment_scope.clear()
            for deployment_id in ids:
                meta = deployments[deployment_id]
                label = meta.get("label") if isinstance(meta.get("label"), str) else deployment_id
                target = meta.get("railgun_target_identity") or {}
                destination = f"{target.get('host', '?')}:{target.get('port', '?')} · {meta.get('universe', '?')}"
                item = QTreeWidgetItem((f"{label} [{deployment_id}]", *("" for _ in self.operation_checkboxes), destination))
                item.setToolTip(0, f"{label} [{deployment_id}]")
                item.setToolTip(self._destination_column, destination)
                item.setData(0, Qt.ItemDataRole.UserRole, deployment_id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                for operation in self.operation_checkboxes:
                    self.set_deployment_selection(item, operation,
                        deployment_id in policy.permissions[operation].deployment_ids)
                self.deployment_scope.addTopLevelItem(item)
            self._loading = False
            self._sync_enabled_state()
            if warning:
                self.summary.setText(warning)
        except RuntimeError:
            self.setEnabled(False)
            self.summary.setText("Unlock a Vault to author Terminal access.")
        finally:
            self._loading = False

    def supports_operation(self, operation):
        return not self._access_mode or operation not in self._AI_UNAVAILABLE_OPERATIONS

    def set_deployment_selection(self, item, operation, selected):
        """Unavailable columns show status rather than a selectable checkbox."""
        column = tuple(self.operation_checkboxes).index(operation) + 1
        if not self.supports_operation(operation):
            label, tooltip = self._AI_UNAVAILABLE_OPERATIONS[operation]
            item.setData(column, Qt.ItemDataRole.CheckStateRole, None)
            item.setText(column, label)
            item.setToolTip(column, tooltip)
            return
        item.setText(column, "")
        item.setCheckState(column,
            Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)

    def _selected_deployment_ids(self, column=1) -> list[str]:
        operation = tuple(self.operation_checkboxes)[column - 1]
        if not self.supports_operation(operation):
            return []
        return [
            self.deployment_scope.topLevelItem(index).data(
                0, Qt.ItemDataRole.UserRole
            )
            for index in range(self.deployment_scope.topLevelItemCount())
            if self.deployment_scope.topLevelItem(index).checkState(column)
            == Qt.CheckState.Checked
        ]

    def _sync_enabled_state(self):
        enabled = self.enabled_checkbox.isChecked()
        self.lifetime_seconds.setEnabled(enabled)
        for checkbox in self.operation_checkboxes.values():
            checkbox.setEnabled(enabled)
        if self._access_mode:
            for checkbox in (self.alerts_checkbox, self.railgun_checkbox):
                checkbox.setChecked(False)
                checkbox.setEnabled(False)
        self.deployment_scope.setEnabled(enabled and any(c.isChecked() for c in self.operation_checkboxes.values()))
        if self._loading:
            return
        if not enabled:
            self.summary.setText("AI access is off; saving grants nothing." if self._access_mode
                                 else "Terminal access is off; saving grants nothing.")
        elif not any(c.isChecked() for c in self.operation_checkboxes.values()):
            self.summary.setText("Approval may be requested, but no operation is permitted.")
        else:
            scopes = "; ".join(f"{operation}: {len(self._selected_deployment_ids(column))}"
                for column, (operation, checkbox) in enumerate(self.operation_checkboxes.items(), 1)
                if checkbox.isChecked())
            self.summary.setText(
                f"Prepared deployment scopes — {scopes}; "
                f"approval expires within {self.lifetime_seconds.value()} seconds."
                + self._inspection_summary()
            )

    def _inspection_summary(self):
        if not self.enabled_checkbox.isChecked() or not self.logs_checkbox.isChecked():
            return ""
        columns = {operation: column for column, operation in enumerate(self.operation_checkboxes, 1)}
        logs = set(self._selected_deployment_ids(columns["logs.read"]))
        agents = set(self._selected_deployment_ids(columns["agents.list"])) if self.agents_checkbox.isChecked() else set()
        missing = logs - agents
        if missing:
            return (f" Swarm inspection is unavailable for {len(missing)} log-enabled deployment(s): "
                    "enable agent inventory above and select the same deployment in Agents.")
        return f" Swarm inspection prepared for {len(logs & agents)} deployment(s)."

    def save_policy(self):
        try:
            ids = deployment_ids(self._authority().read())
            permissions = {}
            for column, (operation, checkbox) in enumerate(self.operation_checkboxes.items(), 1):
                selected = self._selected_deployment_ids(column)
                if self.enabled_checkbox.isChecked() and checkbox.isChecked() and not selected:
                    raise TerminalAccessPolicyError(f"Select at least one prepared deployment for {operation}")
                supported = self.supports_operation(operation)
                permissions[operation] = {"enabled": checkbox.isChecked() and supported,
                                          "deployment_ids": selected if supported else []}
            record = {
                "schema_version": 1,
                "enabled": self.enabled_checkbox.isChecked(),
                "approval_lifetime_seconds": self.lifetime_seconds.value(),
                "permissions": permissions,
            }
            policy = validate_policy(record, ids)
            if self._access_mode:
                self._authority().access_control.set_policy(enabled=policy.enabled,
                    approval_lifetime_seconds=policy.approval_lifetime_seconds,
                    permissions=policy.to_record()["permissions"])
            elif not self._authority().patch(SECTION_KEY, policy.to_record()):
                raise RuntimeError("Vault writer rejected the update")
            self.summary.setText(
                ("AI policy saved; previous approvals revoked. Open AI access to accept new requests."
                 if self._access_mode else "Terminal access policy saved. No listener or client access was started.")
                + self._inspection_summary()
            )
        except (RuntimeError, ValueError, PermissionError) as exc:
            name = "AI" if self._access_mode else "Terminal"
            self.summary.setText(f"{name} access policy was not saved: {exc}")


class TerminalAccessPanel(QWidget):
    """Compatibility wrapper for layouts that require a plain QWidget."""

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.controls = TerminalAccessControls(self, **kwargs)
        layout.addWidget(self.controls)
