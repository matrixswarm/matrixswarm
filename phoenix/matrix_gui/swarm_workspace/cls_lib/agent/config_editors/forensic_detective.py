from .base_editor import BaseEditor
from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit,
    QSpinBox, QCheckBox, QFormLayout
)

class ForensicDetective(BaseEditor):

    def _build_form(self):
        cfg = self.config

        # ===============================
        # ALERTING
        # ===============================
        alert_box = QWidget()
        al = QFormLayout(alert_box)
        al.setContentsMargins(0, 0, 0, 0)

        self.alert_cooldown = QSpinBox()
        self.alert_cooldown.setRange(0, 86400)
        self.alert_cooldown.setValue(cfg.get("alert_cooldown_sec", 300))

        self.alert_to_role = QLineEdit(
            cfg.get("alert_to_role", "hive.alert")
        )

        al.addRow("Alert Cooldown (sec):", self.alert_cooldown)
        al.addRow("Alert To Role:", self.alert_to_role)

        self.layout.addRow(QLabel("🚨 Alerting"))
        self.layout.addRow(alert_box)

        # ===============================
        # ORACLE ANALYSIS
        # ===============================
        oracle_cfg = cfg.get("oracle_analysis", {})

        oracle_box = QWidget()
        ol = QFormLayout(oracle_box)
        ol.setContentsMargins(0, 0, 0, 0)

        self.enable_oracle = QCheckBox("Enable Oracle Analysis")
        self.enable_oracle.setChecked(
            bool(oracle_cfg.get("enable_oracle", 0))
        )

        self.oracle_role = QLineEdit(
            oracle_cfg.get("role", "hive.oracle")
        )

        ol.addRow(self.enable_oracle)
        ol.addRow("Oracle Role:", self.oracle_role)

        self.layout.addRow(QLabel("🧠 Oracle Analysis"))
        self.layout.addRow(oracle_box)

    def _save(self):
        self.node.config.update({
            "alert_cooldown_sec": self.alert_cooldown.value(),
            "alert_to_role": self.alert_to_role.text().strip(),
            "oracle_analysis": {
                "enable_oracle": int(self.enable_oracle.isChecked()),
                "role": self.oracle_role.text().strip()
            }
        })

        self.node.mark_dirty()
        self.accept()
