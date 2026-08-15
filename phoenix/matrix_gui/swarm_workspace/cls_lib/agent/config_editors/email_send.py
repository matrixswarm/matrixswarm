# Commander & ChatGPT – Victory Always Edition
# EMAIL SEND Config Editor
from PyQt6.QtWidgets import QCheckBox, QFormLayout, QLabel, QWidget

from .base_editor import BaseEditor
from .mixin.service_roles_mixin import ServiceRolesMixin


class EmailSend(BaseEditor, ServiceRolesMixin):
    """Edit alert-payload protection without exposing assigned key material."""

    def _build_form(self):
        cfg = self.config

        security_box = QWidget()
        form = QFormLayout(security_box)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)

        self.encrypt_alerts = QCheckBox("Encrypt alert email subject and body")
        self.encrypt_alerts.setChecked(bool(cfg.get("encrypt_alerts", False)))
        form.addRow(self.encrypt_alerts)

        explanation = QLabel(
            "Uses this agent's assigned packet signing keys. "
            "If secure wrapping fails, the alert is not sent in plaintext."
        )
        explanation.setWordWrap(True)
        form.addRow(explanation)

        self.layout.addRow(QLabel("🔐 Email Alert Security"))
        self.layout.addRow(security_box)

        self.layout.addRow(QLabel("🔗 Service Manager Roles"))
        self._build_roles_section(cfg, default_role="hive.alert@cmd_send_alert_msg")

    def _save(self):
        roles = self._collect_roles(default_role="hive.alert@cmd_send_alert_msg")

        service_manager = self.node.config.get("service-manager", [])
        if service_manager and isinstance(service_manager, list) and isinstance(service_manager[0], dict):
            first = dict(service_manager[0])
            first["role"] = roles
            service_manager = [first, *service_manager[1:]]
        else:
            service_manager = [{"role": roles}]

        self.node.config.update({
            "encrypt_alerts": self.encrypt_alerts.isChecked(),
            "service-manager": service_manager,
        })
        self.node.mark_dirty()
        self.accept()
