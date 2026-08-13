from .base_editor import BaseEditor
from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit,
    QSpinBox, QFormLayout
)

class MySQLWatchdog(BaseEditor):

    def _build_form(self):
        cfg = self.config

        # ===============================
        # GENERAL
        # ===============================
        gen = QWidget()
        gl = QFormLayout(gen)

        self.interval = QSpinBox()
        self.interval.setRange(1, 3600)
        self.interval.setValue(cfg.get("check_interval_sec", 20))

        self.service_name = QLineEdit(
            cfg.get("service_name", "mysql")
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
        # MYSQL CONNECTION
        # ===============================
        db = QWidget()
        dl = QFormLayout(db)

        self.mysql_port = QSpinBox()
        self.mysql_port.setRange(1, 65535)
        self.mysql_port.setValue(cfg.get("mysql_port", 3306))

        self.socket_path = QLineEdit(
            cfg.get("socket_path", "/var/run/mysqld/mysqld.sock")
        )

        dl.addRow("MySQL Port:", self.mysql_port)
        dl.addRow("Socket Path:", self.socket_path)

        self.layout.addRow(QLabel("🗄️ MySQL Connection"))
        self.layout.addRow(db)

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

        # ===============================
        # THRESHOLDS
        # ===============================
        thresholds = cfg.get("alert_thresholds", {})

        th = QWidget()
        tl = QFormLayout(th)

        self.uptime_min = QSpinBox()
        self.uptime_min.setRange(0, 100)
        self.uptime_min.setValue(
            thresholds.get("uptime_pct_min", 90)
        )

        self.slow_restart = QSpinBox()
        self.slow_restart.setRange(0, 300)
        self.slow_restart.setValue(
            thresholds.get("slow_restart_sec", 10)
        )

        tl.addRow("Min Uptime %:", self.uptime_min)
        tl.addRow("Slow Restart (sec):", self.slow_restart)

        self.layout.addRow(QLabel("📊 Alert Thresholds"))
        self.layout.addRow(th)

    def _save(self):
        self.node.config.update({
            "check_interval_sec": self.interval.value(),
            "service_name": self.service_name.text().strip(),
            "mysql_port": self.mysql_port.value(),
            "socket_path": self.socket_path.text().strip(),
            "restart_limit": self.restart_limit.value(),
            "alert_cooldown": self.alert_cooldown.value(),
            "alert_to_role": self.alert_to_role.text().strip() or None,
            "report_to_role": self.report_to_role.text().strip() or None,
            "alert_thresholds": {
                "uptime_pct_min": self.uptime_min.value(),
                "slow_restart_sec": self.slow_restart.value()
            }
        })

        self.node.mark_dirty()
        self.accept()
