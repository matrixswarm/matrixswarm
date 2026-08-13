from .base_editor import BaseEditor
from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit,
    QSpinBox, QCheckBox, QFormLayout
)

class RedisWatchdog(BaseEditor):

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
            cfg.get("service_name", "redis")
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
        # REDIS CONNECTION
        # ===============================
        conn = QWidget()
        cl = QFormLayout(conn)

        self.redis_port = QSpinBox()
        self.redis_port.setRange(1, 65535)
        self.redis_port.setValue(cfg.get("redis_port", 6379))

        self.socket_path = QLineEdit(
            cfg.get("socket_path", "/var/run/redis/redis-server.sock")
        )

        cl.addRow("Redis Port:", self.redis_port)
        cl.addRow("Socket Path:", self.socket_path)

        self.layout.addRow(QLabel("🧠 Redis Connection"))
        self.layout.addRow(conn)

        # ===============================
        # ALERTING
        # ===============================
        alert = QWidget()
        al = QFormLayout(alert)

        self.always_alert = QCheckBox("Always alert on failure")
        self.always_alert.setChecked(
            bool(cfg.get("always_alert", 0))
        )

        self.alert_to_role = QLineEdit(
            cfg.get("alert_to_role", "")
        )

        self.report_to_role = QLineEdit(
            cfg.get("report_to_role", "")
        )

        al.addRow(self.always_alert)
        al.addRow("Alert To Role:", self.alert_to_role)
        al.addRow("Report To Role:", self.report_to_role)

        self.layout.addRow(QLabel("🚨 Alerting"))
        self.layout.addRow(alert)

    def _save(self):
        self.node.config.update({
            "check_interval_sec": self.interval.value(),
            "service_name": self.service_name.text().strip(),
            "redis_port": self.redis_port.value(),
            "socket_path": self.socket_path.text().strip(),
            "restart_limit": self.restart_limit.value(),
            "always_alert": int(self.always_alert.isChecked()),
            "alert_to_role": self.alert_to_role.text().strip() or None,
            "report_to_role": self.report_to_role.text().strip() or None,
        })

        self.node.mark_dirty()
        self.accept()
