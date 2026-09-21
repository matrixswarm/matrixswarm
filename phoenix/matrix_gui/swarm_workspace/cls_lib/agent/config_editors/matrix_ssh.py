"""Typed Phoenix configuration editor for the Matrix SSH ingress agent."""

from PyQt6.QtWidgets import QCheckBox, QFormLayout, QLabel, QSpinBox, QWidget

from .base_editor import BaseEditor
from .mixin.service_roles_mixin import ServiceRolesMixin


def _display_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


class MatrixSsh(BaseEditor, ServiceRolesMixin):
    def _build_form(self):
        cfg = self.config
        general_box = QWidget()
        form = QFormLayout(general_box)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)

        self.poll_interval = QSpinBox()
        self.poll_interval.setRange(1, 3600)
        self.poll_interval.setValue(int(cfg.get("poll_interval", 1)))
        form.addRow("Poll Interval (sec):", self.poll_interval)

        self.batch_limit = QSpinBox()
        self.batch_limit.setRange(1, 128)
        self.batch_limit.setValue(int(cfg.get("batch_limit", 32)))
        form.addRow("Packets Per Poll:", self.batch_limit)

        self.lockdown_checkbox = QCheckBox(
            "Enable Lockdown (Disable Packet Processing)"
        )
        self.lockdown_checkbox.setChecked(
            _display_bool(cfg.get("lockdown_state", False))
        )
        form.addRow(self.lockdown_checkbox)

        self.lockdown_time = QSpinBox()
        self.lockdown_time.setRange(0, 86400)
        self.lockdown_time.setValue(int(cfg.get("lockdown_time", 0)))
        form.addRow("Lockdown Duration (sec):", self.lockdown_time)

        self.layout.addRow(QLabel("🛡️ Matrix SSH Settings"))
        self.layout.addRow(general_box)
        self.layout.addRow(QLabel("🔗 Service Manager Roles"))
        self._build_roles_section(cfg, default_role="matrix_ssh.status@cmd_status")

    def _save(self):
        self.node.config.update(
            {
                "poll_interval": int(self.poll_interval.value()),
                "batch_limit": int(self.batch_limit.value()),
                "lockdown_state": self.lockdown_checkbox.isChecked(),
                "lockdown_time": int(self.lockdown_time.value()),
                "service-manager": [{"role": self._collect_roles()}],
            }
        )
        self.node.mark_dirty()
        self.accept()
