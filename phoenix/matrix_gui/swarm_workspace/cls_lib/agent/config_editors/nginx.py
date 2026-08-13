from .base_editor import BaseEditor
from .mixin.list_editor_mixin import ListEditorMixin
from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit,
    QSpinBox, QFormLayout
)

class NginxWatchdogEditor(BaseEditor, ListEditorMixin):

    def _build_form(self):
        cfg = self.config

        # ===============================
        # GENERAL
        # ===============================
        gen = QWidget()
        gl = QFormLayout(gen)

        self.interval = QSpinBox()
        self.interval.setRange(1, 3600)
        self.interval.setValue(cfg.get("check_interval_sec", 10))

        self.service_name = QLineEdit(
            cfg.get("service_name", "nginx")
        )

        self.restart_limit = QSpinBox()
        self.restart_limit.setRange(0, 20)
        self.restart_limit.setValue(cfg.get("restart_limit", 3))

        gl.addRow("Check Interval (sec):", self.interval)
        gl.addRow("Service Name:", self.service_name)
        gl.addRow("Restart Limit:", self.restart_limit)

        self.layout.addRow(QLabel("🛠️ General"))
        self.layout.addRow(gen)

        # ===============================
        # PORTS
        # ===============================
        ports_data = [{"port": p} for p in cfg.get("ports", [80, 443])]
        self._build_list_section(
            label="🌐 Ports",
            data=ports_data,
            columns=["port"],
            attr_name="ports"
        )

        # ===============================
        # ALERTING
        # ===============================
        alert = QWidget()
        al = QFormLayout(alert)

        self.alert_cooldown = QSpinBox()
        self.alert_cooldown.setRange(0, 86400)
        self.alert_cooldown.setValue(cfg.get("alert_cooldown", 300))

        self.alert_to_role = QLineEdit(
            cfg.get("alert_to_role", "")
        )

        self.report_to_role = QLineEdit(
            cfg.get("report_to_role", "")
        )

        al.addRow("Alert Cooldown (sec):", self.alert_cooldown)
        al.addRow("Alert To Role:", self.alert_to_role)
        al.addRow("Report To Role:", self.report_to_role)

        self.layout.addRow(QLabel("🚨 Alerting"))
        self.layout.addRow(alert)

    def _save(self):
        ports = [int(x["port"]) for x in self._collect_list_data("ports")]

        self.node.config.update({
            "check_interval_sec": self.interval.value(),
            "service_name": self.service_name.text().strip(),
            "ports": ports,
            "restart_limit": self.restart_limit.value(),
            "alert_cooldown": self.alert_cooldown.value(),
            "alert_to_role": self.alert_to_role.text().strip() or None,
            "report_to_role": self.report_to_role.text().strip() or None,
        })

        self.node.mark_dirty()
        self.accept()
