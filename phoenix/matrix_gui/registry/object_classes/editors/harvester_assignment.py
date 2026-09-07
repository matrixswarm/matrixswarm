"""Vault-backed Harvester hive and SSH assignment editor."""

import re

from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from matrix_gui.modules.vault.services.vault_core_singleton import (
    VaultCoreSingleton,
)

from .base_editor import BaseEditor
from .ssh import SSH


_UNIVERSE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_DEPLOYMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_CAPABILITIES = {"contact_only"}
_FORBIDDEN_TEXT = re.compile(r"[\x00\r\n]")


class HarvesterAssignment(BaseEditor):
    """Pair one Phoenix deployment with one Registry SSH object."""

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, default_channel_options)
        self._loading = False

        self.label = QLineEdit(self.generate_default_label())
        self.deployment = QComboBox()
        self.ssh = QComboBox()
        self.capability = QComboBox()
        self.capability.addItem(
            "Contact only (resurrection deferred)", "contact_only"
        )
        self.note = QLineEdit()
        self.minimum_agents = self._spin(1, 1, 10_000)
        self.failure_threshold = self._spin(3, 1, 20)
        self.recovery_threshold = self._spin(3, 1, 20)
        self.alert_cooldown = self._spin(300, 0, 86_400)
        self.recovery_attempt_limit = self._spin(3, 1, 10)
        self.recovery_cooldown = self._spin(60, 10, 3_600)
        self.path_selector = QComboBox()
        self.path_selector.addItem("config")

        pairing = QWidget()
        pairing_layout = QHBoxLayout(pairing)
        pairing_layout.setContentsMargins(0, 0, 0, 0)
        pairing_layout.addWidget(self.deployment)
        pairing_layout.addWidget(self.ssh)

        layout = QFormLayout(self)
        layout.addRow("Label", self.label)
        layout.addRow("Hive ↔ SSH", pairing)
        layout.addRow("Authority", self.capability)
        layout.addRow("Note", self.note)
        layout.addRow("Minimum Agents", self.minimum_agents)
        layout.addRow("Failure Threshold", self.failure_threshold)
        layout.addRow("Recovery Threshold", self.recovery_threshold)
        layout.addRow("Alert Cooldown (sec)", self.alert_cooldown)
        layout.addRow("Resurrection Attempt Limit", self.recovery_attempt_limit)
        layout.addRow("Resurrection Retry (sec)", self.recovery_cooldown)
        layout.addRow("Directive Path", self.path_selector)
        layout.addRow("Serial", self.serial)

        self._populate_deployments()
        self._populate_ssh()
        self.deployment.currentIndexChanged.connect(self._sync_ssh_to_hive)
        self.capability.currentIndexChanged.connect(self._render_capability)
        self._sync_ssh_to_hive()
        self._render_capability()

    @staticmethod
    def _spin(value, minimum, maximum):
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        return widget

    @staticmethod
    def _vault_sections():
        vault = VaultCoreSingleton.get()
        deployments = vault.get_section("deployments")
        registry = vault.get_store("registry")
        ssh = registry.get_namespace("ssh")
        return deployments, ssh

    def _populate_deployments(self):
        deployments, _ssh = self._vault_sections()
        self.deployment.clear()
        self.deployment.addItem("Select hive…", None)
        for deployment_id, record in deployments.items():
            if not isinstance(record, dict):
                continue
            label = str(record.get("label") or deployment_id)
            universe = self._deployment_universe(record)
            suffix = f" [{universe}]" if universe else ""
            self.deployment.addItem(f"{label}{suffix}", str(deployment_id))

    def _populate_ssh(self):
        _deployments, ssh_records = self._vault_sections()
        self.ssh.clear()
        self.ssh.addItem("Select SSH…", None)
        for serial, record in ssh_records.items():
            if not isinstance(record, dict):
                continue
            label = str(record.get("label") or serial)
            host = str(record.get("host") or "unknown-host")
            username = str(record.get("username") or "unknown-user")
            self.ssh.addItem(
                f"{label} [{username}@{host}]",
                str(serial),
            )

    @staticmethod
    def _deployment_universe(deployment):
        universe = deployment.get("universe")
        if isinstance(universe, str) and universe.strip():
            return universe.strip()
        encrypted_path = deployment.get("encrypted_path")
        if not isinstance(encrypted_path, str):
            return ""
        filename = encrypted_path.replace("\\", "/").rsplit("/", 1)[-1]
        suffix = ".enc.json"
        return filename[: -len(suffix)] if filename.endswith(suffix) else ""

    def _sync_ssh_to_hive(self):
        if self._loading:
            return
        deployment_id = self.deployment.currentData()
        deployments, _ssh = self._vault_sections()
        deployment = deployments.get(deployment_id, {})
        if not isinstance(deployment, dict):
            return
        ssh_serial = deployment.get("ssh_serial")
        index = self.ssh.findData(str(ssh_serial)) if ssh_serial else -1
        if index >= 0:
            self.ssh.setCurrentIndex(index)

    def _render_capability(self):
        self.recovery_attempt_limit.setEnabled(False)
        self.recovery_cooldown.setEnabled(False)

    def on_load(self, data):
        self._loading = True
        try:
            self.label.setText(str(data.get("label", "")))
            self.serial.setText(str(data.get("serial", "")))
            deployment_index = self.deployment.findData(
                str(data.get("deployment_id", ""))
            )
            if deployment_index >= 0:
                self.deployment.setCurrentIndex(deployment_index)
            ssh_index = self.ssh.findData(str(data.get("ssh_serial", "")))
            if ssh_index >= 0:
                self.ssh.setCurrentIndex(ssh_index)
            capability_index = self.capability.findData(
                data.get("capability", "contact_only")
            )
            if capability_index >= 0:
                self.capability.setCurrentIndex(capability_index)
            self.note.setText(str(data.get("note", "")))
            self.minimum_agents.setValue(int(data.get("minimum_agents", 1)))
            self.failure_threshold.setValue(int(data.get("failure_threshold", 3)))
            self.recovery_threshold.setValue(int(data.get("recovery_threshold", 3)))
            self.alert_cooldown.setValue(int(data.get("alert_cooldown_sec", 300)))
            self.recovery_attempt_limit.setValue(
                int(data.get("recovery_attempt_limit", 3))
            )
            self.recovery_cooldown.setValue(
                int(data.get("recovery_cooldown_sec", 60))
            )
        finally:
            self._loading = False
        self._render_capability()

    def serialize(self):
        self._ensure_serial()
        deployment_id = self.deployment.currentData()
        ssh_serial = self.ssh.currentData()
        return {
            "node_directive_path": "config",
            "serial": self.serial.text().strip(),
            "label": self.label.text().strip(),
            "deployment_id": deployment_id,
            "deployment_label": self.deployment.currentText(),
            "ssh_serial": ssh_serial,
            "ssh_label": self.ssh.currentText(),
            "capability": self.capability.currentData(),
            "note": self.note.text().strip(),
            "minimum_agents": self.minimum_agents.value(),
            "failure_threshold": self.failure_threshold.value(),
            "recovery_threshold": self.recovery_threshold.value(),
            "alert_cooldown_sec": self.alert_cooldown.value(),
            "recovery_attempt_limit": self.recovery_attempt_limit.value(),
            "recovery_cooldown_sec": self.recovery_cooldown.value(),
        }

    def deploy_fields(self):
        ok, message = self.is_validated()
        if not ok:
            raise ValueError(message)

        deployments, ssh_records = self._vault_sections()
        deployment_id = str(self.deployment.currentData())
        ssh_serial = str(self.ssh.currentData())
        deployment = deployments[deployment_id]
        ssh_record = ssh_records[ssh_serial]
        universe = self._deployment_universe(deployment)

        ssh_editor = SSH(new_conn=False)
        ssh_editor._load_data(ssh_record)
        ssh_fields = ssh_editor.deploy_fields()

        capability = self.capability.currentData()
        target = {
            "id": deployment_id,
            "deployment_id": deployment_id,
            "universe": universe,
            "note": self.note.text().strip(),
            "minimum_agents": self.minimum_agents.value(),
            "failure_threshold": self.failure_threshold.value(),
            "recovery_threshold": self.recovery_threshold.value(),
            "alert_cooldown_sec": self.alert_cooldown.value(),
            "recovery_mode": "disabled",
        }
        return {
            "mode": "ssh",
            "ssh": ssh_fields,
            "targets": [target],
            "automatic_recovery_enabled": False,
        }

    def is_validated(self):
        deployment_id = self.deployment.currentData()
        ssh_serial = self.ssh.currentData()
        if not deployment_id:
            return False, "Select a hive deployment."
        if not ssh_serial:
            return False, "Select its matching SSH registry object."
        if not _DEPLOYMENT_ID.fullmatch(str(deployment_id)):
            return False, "The selected hive has an invalid deployment ID."

        label = self.label.text().strip()
        note = self.note.text().strip()
        if not label:
            return False, "Label is required."
        if len(label) > 128 or _FORBIDDEN_TEXT.search(label):
            return False, "Label must be 128 safe characters or fewer."
        if len(note) > 128 or _FORBIDDEN_TEXT.search(note):
            return False, "Note must be 128 safe characters or fewer."

        capability = self.capability.currentData()
        if capability not in _CAPABILITIES:
            return False, "Select a valid Harvester authority."

        serial_ok, serial_message = self._require_serial()
        if not serial_ok:
            return serial_ok, serial_message

        deployments, ssh_records = self._vault_sections()
        deployment = deployments.get(str(deployment_id))
        ssh_record = ssh_records.get(str(ssh_serial))
        if not isinstance(deployment, dict):
            return False, "The selected hive no longer exists in the vault."
        if not isinstance(ssh_record, dict):
            return False, "The selected SSH object no longer exists in the registry."
        universe = self._deployment_universe(deployment)
        if not _UNIVERSE.fullmatch(universe):
            return False, "The selected hive has an invalid universe name."
        recorded_ssh = deployment.get("ssh_serial")
        if recorded_ssh and str(recorded_ssh) != str(ssh_serial):
            return False, "The selected SSH object does not match this hive."

        ssh_editor = SSH(new_conn=False)
        ssh_editor._load_data(ssh_record)
        ssh_ok, ssh_message = ssh_editor.is_validated()
        if not ssh_ok:
            return False, f"SSH object is invalid: {ssh_message}"

        return True, ""
