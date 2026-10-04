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

    def __init__(self, parent=None, *, vault_authority=None, terminal_mode=False):
        super().__init__("Terminal access", parent)
        self.setObjectName("TerminalAccessControls")
        self._vault_authority = vault_authority
        self._terminal_mode = terminal_mode is True
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
        self.operation_checkboxes = {
            "alerts.read": self.alerts_checkbox,
            "swarms.list": self.swarms_checkbox,
            "railgun.launch": self.railgun_checkbox,
        }
        for operation, checkbox in tuple(self.operation_checkboxes.items())[1:]:
            checkbox.setObjectName("Terminal" + operation.replace(".", "_") + "Enabled")
            checkbox.setToolTip("Fixed saved Registry SSH target only; no alternate server, shell, kill, or restart authority.")
            checkbox.toggled.connect(self._sync_enabled_state)
            layout.addWidget(checkbox)

        self.deployment_scope = QTreeWidget()
        self.deployment_scope.setObjectName("TerminalAlertDeploymentScope")
        self.deployment_scope.setHeaderLabels(("Prepared deployment", "Alert reads", "Swarms inventory", "Railgun launch", "Fixed destination"))
        header = self.deployment_scope.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
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
                policy = validate_policy(vault.get(SECTION_KEY), ids)
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
                item = QTreeWidgetItem((f"{label} [{deployment_id}]", "", "", "", destination))
                item.setToolTip(0, f"{label} [{deployment_id}]")
                item.setToolTip(4, destination)
                item.setData(0, Qt.ItemDataRole.UserRole, deployment_id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                for column, operation in enumerate(self.operation_checkboxes, 1):
                    item.setCheckState(column, Qt.CheckState.Checked
                        if deployment_id in policy.permissions[operation].deployment_ids
                        else Qt.CheckState.Unchecked)
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

    def _selected_deployment_ids(self, column=1) -> list[str]:
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
        self.deployment_scope.setEnabled(enabled and any(c.isChecked() for c in self.operation_checkboxes.values()))
        if self._loading:
            return
        if not enabled:
            self.summary.setText("Terminal access is off; saving grants nothing.")
        elif not any(c.isChecked() for c in self.operation_checkboxes.values()):
            self.summary.setText("Approval may be requested, but no operation is permitted.")
        else:
            scopes = "; ".join(f"{operation}: {len(self._selected_deployment_ids(column))}"
                for column, (operation, checkbox) in enumerate(self.operation_checkboxes.items(), 1)
                if checkbox.isChecked())
            self.summary.setText(
                f"Prepared deployment scopes — {scopes}; "
                f"approval expires within {self.lifetime_seconds.value()} seconds."
            )

    def save_policy(self):
        try:
            ids = deployment_ids(self._authority().read())
            permissions = {}
            for column, (operation, checkbox) in enumerate(self.operation_checkboxes.items(), 1):
                selected = self._selected_deployment_ids(column)
                if self.enabled_checkbox.isChecked() and checkbox.isChecked() and not selected:
                    raise TerminalAccessPolicyError(f"Select at least one prepared deployment for {operation}")
                permissions[operation] = {"enabled": checkbox.isChecked(), "deployment_ids": selected}
            record = {
                "schema_version": 1,
                "enabled": self.enabled_checkbox.isChecked(),
                "approval_lifetime_seconds": self.lifetime_seconds.value(),
                "permissions": permissions,
            }
            policy = validate_policy(record, ids)
            if not self._authority().patch(SECTION_KEY, policy.to_record()):
                raise RuntimeError("Vault writer rejected the update")
            self.summary.setText(
                "Terminal access policy saved. No listener or client access was started."
            )
        except (RuntimeError, TerminalAccessPolicyError) as exc:
            self.summary.setText(f"Terminal access policy was not saved: {exc}")


class TerminalAccessPanel(QWidget):
    """Compatibility wrapper for layouts that require a plain QWidget."""

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.controls = TerminalAccessControls(self, **kwargs)
        layout.addWidget(self.controls)
