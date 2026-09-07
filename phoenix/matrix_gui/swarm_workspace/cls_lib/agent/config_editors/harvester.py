"""Phoenix editor for one server-side Harvester target."""

from pathlib import Path
import re

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QWidget,
)

from matrix_gui.modules.vault.services.vault_core_singleton import (
    VaultCoreSingleton,
)

from .base_editor import BaseEditor


class Harvester(BaseEditor):
    """Configure one watched deployment without loading its swarm key."""

    def _build_form(self):
        cfg = self.config or {}
        target = (cfg.get("targets") or [{}])[0]
        self._deployments = self._read_deployments()
        general = QWidget()
        layout = QFormLayout(general)

        self.enabled = QCheckBox("Enable matrixd checks")
        self.enabled.setChecked(cfg.get("enabled") is True)
        self.mode = QComboBox()
        self.mode.addItems(["local", "ssh"])
        self.mode.setCurrentText(cfg.get("mode", "local"))
        self.interval = QSpinBox()
        self.interval.setRange(5, 3_600)
        self.interval.setValue(int(cfg.get("check_interval_sec", 30)))
        self.timeout = QSpinBox()
        self.timeout.setRange(2, 300)
        self.timeout.setValue(int(cfg.get("matrixd_timeout_sec", 60)))
        self.alert_role = QLineEdit(cfg.get("alert_to_role", "hive.alert"))

        layout.addRow(self.enabled)
        layout.addRow("Matrixd Host:", self.mode)
        layout.addRow("Check Interval (sec):", self.interval)
        layout.addRow("Matrixd Timeout (sec):", self.timeout)
        layout.addRow("Alert Role:", self.alert_role)
        self.layout.addRow(QLabel("Harvester Policy"))
        self.layout.addRow(general)

        target_box = QWidget()
        targets = QFormLayout(target_box)
        self.deployment = QComboBox()
        self.deployment.addItem("Manual observation only", None)
        for deployment_id, deployment in self._deployments.items():
            label = str(deployment.get("label") or deployment_id)
            universe = self._deployment_universe(deployment)
            suffix = f" [{universe}]" if universe else ""
            self.deployment.addItem(f"{label}{suffix}", deployment_id)
        self.target_id = QLineEdit(target.get("id", ""))
        self.universe = QLineEdit(target.get("universe", ""))
        self.note = QLineEdit(target.get("note", ""))
        self.minimum_agents = self._spin(target, "minimum_agents", 1, 1, 10_000)
        self.failure_threshold = self._spin(target, "failure_threshold", 3, 1, 20)
        self.recovery_threshold = self._spin(target, "recovery_threshold", 3, 1, 20)
        self.alert_cooldown = self._spin(
            target, "alert_cooldown_sec", 300, 0, 86_400
        )
        self.vault_binding = QLabel(
            "Observation only. Phoenix binds the deployment identity and SSH "
            "registry profile; no target swarm key is loaded."
        )
        self.vault_binding.setWordWrap(True)

        targets.addRow("Phoenix Deployment:", self.deployment)
        targets.addRow("Target ID:", self.target_id)
        targets.addRow("Universe:", self.universe)
        targets.addRow("Note:", self.note)
        targets.addRow("Minimum Agents:", self.minimum_agents)
        targets.addRow("Failure Threshold:", self.failure_threshold)
        targets.addRow("Recovery Threshold:", self.recovery_threshold)
        targets.addRow("Alert Cooldown (sec):", self.alert_cooldown)
        targets.addRow("Authority:", self.vault_binding)
        self.layout.addRow(QLabel("Assigned Target (one per Harvester agent)"))
        self.layout.addRow(target_box)

        selected_id = target.get("deployment_id")
        selected_index = self.deployment.findData(selected_id)
        if selected_index >= 0:
            self.deployment.setCurrentIndex(selected_index)
        self.deployment.currentIndexChanged.connect(self._deployment_changed)
        self._deployment_changed()

    @staticmethod
    def _read_deployments():
        try:
            deployments = VaultCoreSingleton.get().get_section("deployments")
        except Exception:
            return {}
        if not isinstance(deployments, dict):
            return {}
        return {
            str(deployment_id): {
                "label": deployment.get("label"),
                "encrypted_path": deployment.get("encrypted_path"),
                "ssh_serial": deployment.get("ssh_serial"),
            }
            for deployment_id, deployment in deployments.items()
            if isinstance(deployment, dict)
        }

    @staticmethod
    def _deployment_universe(deployment):
        encrypted_path = deployment.get("encrypted_path")
        if not isinstance(encrypted_path, str):
            return ""
        filename = Path(encrypted_path).name
        suffix = ".enc.json"
        return filename[: -len(suffix)] if filename.endswith(suffix) else ""

    def _deployment_changed(self):
        deployment_id = self.deployment.currentData()
        deployment = self._deployments.get(deployment_id)
        if deployment:
            universe = self._deployment_universe(deployment)
            self.target_id.setText(str(deployment_id))
            self.universe.setText(universe)
            self.target_id.setReadOnly(True)
            self.universe.setReadOnly(True)
        else:
            self.target_id.setReadOnly(False)
            self.universe.setReadOnly(False)

    @staticmethod
    def _spin(config, key, default, minimum, maximum):
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(int(config.get(key, default)))
        return widget

    def _save(self):
        mode = self.mode.currentText()
        deployment_id = self.deployment.currentData()
        deployment = self._deployments.get(deployment_id)
        target_id = str(deployment_id) if deployment else self.target_id.text().strip()
        universe = (
            self._deployment_universe(deployment)
            if deployment
            else self.universe.text().strip()
        )
        if target_id and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", target_id
        ):
            QMessageBox.warning(self, "Harvester Target", "Target ID is invalid.")
            return
        if universe and not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", universe):
            QMessageBox.warning(self, "Harvester Target", "Universe is invalid.")
            return

        self._configure_ssh_constraint(mode, deployment)
        target = {
            "id": target_id,
            "universe": universe,
            "note": self.note.text().strip(),
            "minimum_agents": self.minimum_agents.value(),
            "failure_threshold": self.failure_threshold.value(),
            "recovery_threshold": self.recovery_threshold.value(),
            "alert_cooldown_sec": self.alert_cooldown.value(),
        }
        if deployment:
            target["deployment_id"] = deployment_id
        self.node.config.update(
            {
                "enabled": self.enabled.isChecked(),
                "mode": mode,
                "check_interval_sec": self.interval.value(),
                "matrixd_timeout_sec": self.timeout.value(),
                "alert_to_role": self.alert_role.text().strip(),
                "targets": [target] if target_id and universe else [],
            }
        )
        self.node.mark_dirty()
        self.accept()

    def _configure_ssh_constraint(self, mode, deployment):
        constraints = [
            constraint
            for constraint in self.node.get_constraints()
            if constraint.get("class") == "ssh"
        ]
        if mode == "local":
            if constraints:
                self.node.remove_constraint("ssh")
            return
        if not constraints:
            self.node.add_constraint("ssh")
            constraints = [
                constraint
                for constraint in self.node.get_constraints()
                if constraint.get("class") == "ssh"
            ]
        ssh_serial = deployment.get("ssh_serial") if deployment else None
        if ssh_serial and constraints:
            constraints[0]["serial"] = ssh_serial
            constraints[0]["met"] = True
