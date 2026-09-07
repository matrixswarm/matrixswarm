"""Phoenix editor for Harvester's runtime-wide observation settings."""

from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from .base_editor import BaseEditor


class Harvester(BaseEditor):
    """Edit runtime policy; hive/SSH pairing lives in its constraint."""

    def _build_form(self):
        cfg = self.config or {}
        general = QWidget()
        layout = QFormLayout(general)

        self.enabled = QCheckBox("Enable matrixd checks")
        self.enabled.setChecked(cfg.get("enabled") is True)
        self.interval = QSpinBox()
        self.interval.setRange(5, 3_600)
        self.interval.setValue(int(cfg.get("check_interval_sec", 30)))
        self.timeout = QSpinBox()
        self.timeout.setRange(2, 300)
        self.timeout.setValue(int(cfg.get("matrixd_timeout_sec", 60)))
        self.alert_role = QLineEdit(cfg.get("alert_to_role", "hive.alert"))

        layout.addRow(self.enabled)
        layout.addRow("Check Interval (sec):", self.interval)
        layout.addRow("Matrixd Timeout (sec):", self.timeout)
        layout.addRow("Alert Role:", self.alert_role)
        self.layout.addRow(QLabel("Harvester Policy"))
        self.layout.addRow(general)

    def _save(self):
        for injected_key in (
            "mode",
            "ssh",
            "targets",
            "automatic_recovery_enabled",
        ):
            self.node.config.pop(injected_key, None)
        self.node.config.update(
            {
                "enabled": self.enabled.isChecked(),
                "check_interval_sec": self.interval.value(),
                "matrixd_timeout_sec": self.timeout.value(),
                "alert_to_role": self.alert_role.text().strip(),
            }
        )
        self.node.mark_dirty()
        self.accept()
