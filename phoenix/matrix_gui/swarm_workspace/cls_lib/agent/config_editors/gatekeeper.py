from .base_editor import BaseEditor
from PyQt6.QtWidgets import QLineEdit, QListWidget, QPushButton, QCheckBox, QHBoxLayout, QVBoxLayout, QWidget, QInputDialog

class Gatekeeper(BaseEditor):
    def _build_form(self):
        cfg = self.config

        self.log_path = QLineEdit(cfg.get("log_path", "/var/log/auth.log"))
        self.db_path = QLineEdit(cfg.get("maxmind_db", "GeoLite2-City.mmdb"))
        self.geoip_enabled = QCheckBox()
        self.geoip_enabled.setChecked(bool(cfg.get("geoip_enabled", 1)))
        self.always_alert = QCheckBox()
        self.always_alert.setChecked(bool(cfg.get("always_alert", 1)))
        self.alert_role = QLineEdit(cfg.get("alert_to_role", "hive.alert"))

        self.layout.addRow("Log Path:", self.log_path)
        self.layout.addRow("MaxMind DB:", self.db_path)
        self.layout.addRow("Enable GeoIP:", self.geoip_enabled)
        self.layout.addRow("Always Alert:", self.always_alert)
        self.layout.addRow("Alert Role:", self.alert_role)

        # --- Ignored IPs section ---
        ip_container = QWidget()
        ip_layout = QVBoxLayout(ip_container)
        ip_layout.setContentsMargins(0, 0, 0, 0)
        ip_layout.setSpacing(4)

        self.ignore_ips = QListWidget()
        for ip in cfg.get("ignore_ips", []):
            self.ignore_ips.addItem(ip)
        ip_layout.addWidget(self.ignore_ips)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+")
        rm_btn = QPushButton("–")
        clr_btn = QPushButton("Clear")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(rm_btn)
        btn_row.addWidget(clr_btn)
        ip_layout.addLayout(btn_row)

        # wire up buttons
        add_btn.clicked.connect(self._add_ip)
        rm_btn.clicked.connect(self._remove_ip)
        clr_btn.clicked.connect(self._clear_ips)

        self.layout.addRow("Ignored IPs:", ip_container)

        # Store all fields
        self.inputs = {
            "log_path": self.log_path,
            "maxmind_db": self.db_path,
            "geoip_enabled": self.geoip_enabled,
            "always_alert": self.always_alert,
            "alert_to_role": self.alert_role,
            "ignore_ips": self.ignore_ips,
        }

    # --- Helper methods for list editing ---
    def _add_ip(self):
        ip, ok = QInputDialog.getText(self, "Add IP", "Enter IP address:")
        if ok and ip.strip():
            self.ignore_ips.addItem(ip.strip())

    def _remove_ip(self):
        for item in self.ignore_ips.selectedItems():
            self.ignore_ips.takeItem(self.ignore_ips.row(item))

    def _clear_ips(self):
        self.ignore_ips.clear()

    def _save(self):
        ips = [self.ignore_ips.item(i).text() for i in range(self.ignore_ips.count())]
        self.node.config.update({
            "log_path": self.log_path.text().strip(),
            "maxmind_db": self.db_path.text().strip(),
            "geoip_enabled": int(self.geoip_enabled.isChecked()),
            "always_alert": int(self.always_alert.isChecked()),
            "alert_to_role": self.alert_role.text().strip(),
            "ignore_ips": ips
        })
        self.node.mark_dirty()
        self.accept()