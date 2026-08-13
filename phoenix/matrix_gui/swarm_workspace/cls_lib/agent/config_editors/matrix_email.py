# Commander & ChatGPT – Victory Always Edition
# MATRIX EMAIL Config Editor
# Focused on: poll_interval, msg_retrieval_limit, lockdown_state, lockdown_time
from PyQt6.QtWidgets import (
    QWidget, QLabel, QFormLayout, QSpinBox, QCheckBox
)
from .base_editor import BaseEditor
from .mixin.service_roles_mixin import ServiceRolesMixin

class MatrixEmail(BaseEditor, ServiceRolesMixin):

    def _build_form(self):
        cfg = self.config

        # ---------------------------------------------
        # GENERAL SETTINGS
        # ---------------------------------------------
        general_box = QWidget()
        gl = QFormLayout(general_box)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(4)

        # Poll interval (seconds)
        self.poll_interval = QSpinBox()
        self.poll_interval.setRange(5, 3600)
        self.poll_interval.setValue(int(cfg.get("poll_interval", 20)))
        gl.addRow("Poll Interval (sec):", self.poll_interval)

        # Message retrieval limit
        self.msg_limit = QSpinBox()
        self.msg_limit.setRange(1, 500)
        self.msg_limit.setValue(int(cfg.get("msg_retrieval_limit", 10)))
        gl.addRow("Message Retrieval Limit:", self.msg_limit)

        # Lockdown state toggle
        self.lockdown_checkbox = QCheckBox("Enable Lockdown (Disable Packet Processing)")
        self.lockdown_checkbox.setChecked(bool(cfg.get("lockdown_state", False)))
        gl.addRow(self.lockdown_checkbox)

        # Lockdown duration (seconds)
        self.lockdown_time = QSpinBox()
        self.lockdown_time.setRange(0, 86400)  # 0 = stay down indefinitely
        self.lockdown_time.setValue(int(cfg.get("lockdown_time", 0)))
        gl.addRow("Lockdown Duration (sec):", self.lockdown_time)

        # Add section to layout
        self.layout.addRow(QLabel("📧 Matrix Email Settings"))
        self.layout.addRow(general_box)

        # ---------------------------------------------
        # SERVICE MANAGER ROLES
        # ---------------------------------------------
        self.layout.addRow(QLabel("🔗 Service Manager Roles"))
        self._build_roles_section(cfg, default_role="matrix_email.status@cmd_status")

    # ---------------------------------------------
    # SAVE CONFIG
    # ---------------------------------------------
    def _save(self):
        roles = self._collect_roles()

        self.node.config.update({
            "poll_interval": int(self.poll_interval.value()),
            "msg_retrieval_limit": int(self.msg_limit.value()),
            "lockdown_state": self.lockdown_checkbox.isChecked(),
            "lockdown_time": int(self.lockdown_time.value()),
            "service-manager": [{"role": roles}],
        })

        self.node.mark_dirty()
        self.accept()
