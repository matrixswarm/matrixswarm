"""Workspace configuration for Global Alarm routing and service roles."""
from PyQt6.QtWidgets import QLabel, QLineEdit, QMessageBox, QSpinBox

from .base_editor import BaseEditor
from .mixin.service_roles_mixin import ServiceRolesMixin


class GlobalAlarm(BaseEditor, ServiceRolesMixin):
    def _build_form(self):
        cfg = self.config
        self.interval = QSpinBox()
        self.interval.setRange(1, 60)
        self._load_saved_number(self.interval, cfg.get("interval_sec", 5))
        self.alert_role = QLineEdit()
        self._load_saved_text(self.alert_role, cfg.get("alert_role", "hive.alert"))
        self.layout.addRow("Check interval (seconds):", self.interval)
        self.layout.addRow("Default alert to role:", self.alert_role)
        note = QLabel("New reminders use this role by default. Each reminder can select another "
                      "service role. Relay agents receive alerts when they advertise the matching role.")
        note.setWordWrap(True)
        self.layout.addRow(note)
        self.layout.addRow(QLabel("Service Manager Roles"))
        self._build_roles_section(cfg)

    def _save(self):
        try:
            interval = self._saved_number(self.interval, "Check interval")
            role = self._saved_text(self.alert_role, "Default alert role").strip()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid configuration", str(exc))
            return
        if not role or len(role) > 128 or "@" in role:
            QMessageBox.warning(self, "Invalid configuration", "Enter a service role without a handler, such as hive.alert.")
            return
        self.node.config.update({"interval_sec": interval, "alert_role": role,
            "service-manager": self._service_manager_with_roles(self._collect_roles())})
        self.node.mark_dirty()
        self.accept()
