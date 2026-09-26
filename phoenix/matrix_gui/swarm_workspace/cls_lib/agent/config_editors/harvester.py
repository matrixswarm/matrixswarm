"""Phoenix editor for Harvester's runtime-wide observation settings."""

from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QMessageBox,
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
        self._load_saved_bool(self.enabled, cfg.get("enabled", False))
        self.interval = QSpinBox()
        self.interval.setRange(5, 3_600)
        self._load_saved_number(self.interval, cfg.get("check_interval_sec", 30))
        self.timeout = QSpinBox()
        self.timeout.setRange(2, 300)
        self.timeout.setToolTip(
            "SSH checks run in a supervised process. This is the total deadline "
            "for startup, connection, authentication and the matrixd command; "
            "an expired checker is stopped before retry."
        )
        self._load_saved_number(self.timeout, cfg.get("matrixd_timeout_sec", 60))
        self.alert_role = QLineEdit()
        self._load_saved_text(self.alert_role, cfg.get("alert_to_role", "hive.alert"))

        layout.addRow(self.enabled)
        layout.addRow("Check Interval (sec):", self.interval)
        layout.addRow("Matrixd Timeout (sec):", self.timeout)
        layout.addRow("Alert Role:", self.alert_role)
        self.layout.addRow(QLabel("Harvester Policy"))
        self.layout.addRow(general)

    def _save(self):
        try:
            enabled = self._saved_bool(self.enabled, "Enable matrixd checks")
            alert_role = self._saved_text(self.alert_role, "Alert role")
            interval = self._saved_number(self.interval, "Check interval")
            timeout = self._saved_number(self.timeout, "Matrixd timeout")
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Configuration", str(exc))
            return
        for injected_key in (
            "mode",
            "ssh",
            "targets",
            "automatic_recovery_enabled",
        ):
            self.node.config.pop(injected_key, None)
        self.node.config.update(
            {
                "enabled": enabled,
                "check_interval_sec": interval,
                "matrixd_timeout_sec": timeout,
                "alert_to_role": alert_role.strip(),
            }
        )
        self.node.mark_dirty()
        self.accept()
