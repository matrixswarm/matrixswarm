from .base_editor import BaseEditor
from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QFormLayout
)
from .mixin.service_roles_mixin import ServiceRolesMixin


class StormCrow(BaseEditor, ServiceRolesMixin):
    """
    StormCrow configuration editor
    Mirrors Oracle editor structure.
    """

    def _build_form(self):
        cfg = self.config

        # =======================================================
        # --- ALERT ROUTING SECTION ---
        # =======================================================
        alert_box = QWidget()
        alert_layout = QFormLayout(alert_box)
        alert_layout.setContentsMargins(0, 0, 0, 0)
        alert_layout.setSpacing(4)

        self.alert_to_role = QLineEdit()
        self.alert_to_role.setText(cfg.get("alert_to_role", "hive.alert"))

        alert_layout.addRow("Alert To Role:", self.alert_to_role)

        self.layout.addRow(QLabel("🚨 Alert Routing"))
        self.layout.addRow(alert_box)

        # =======================================================
        # --- LOCATION SECTION ---
        # =======================================================
        location_box = QWidget()
        location_layout = QFormLayout(location_box)
        location_layout.setContentsMargins(0, 0, 0, 0)
        location_layout.setSpacing(4)

        self.zip_code = QLineEdit()
        self.zip_code.setText(cfg.get("zip_code", ""))

        self.latitude = QLineEdit()
        self.latitude.setText(cfg.get("weather_latitude", ""))

        self.longitude = QLineEdit()
        self.longitude.setText(cfg.get("weather_longitude", ""))

        location_layout.addRow("ZIP Code:", self.zip_code)
        location_layout.addRow("Latitude:", self.latitude)
        location_layout.addRow("Longitude:", self.longitude)

        self.layout.addRow(QLabel("📍 Location"))
        self.layout.addRow(location_box)

        # =======================================================
        # --- WEATHER API SECTION ---
        # =======================================================
        api_box = QWidget()
        api_layout = QFormLayout(api_box)
        api_layout.setContentsMargins(0, 0, 0, 0)
        api_layout.setSpacing(4)

        self.alert_endpoint = QLineEdit()
        self.alert_endpoint.setText(
            cfg.get(
                "alert_endpoint",
                "https://api.weather.gov/alerts/active?point"
            )
        )

        api_layout.addRow("Alert Endpoint:", self.alert_endpoint)

        self.layout.addRow(QLabel("🌦️ Weather API"))
        self.layout.addRow(api_box)

        # =======================================================
        # --- SERVICE MANAGER ROLES ---
        # =======================================================
        self.layout.addRow(QLabel("🔗 Service Manager Roles"))
        self._build_roles_section(cfg, default_role="hive.storm_crow")

        # Keep input refs
        self.inputs = {
            "alert_to_role": self.alert_to_role,
            "zip_code": self.zip_code,
            "weather_latitude": self.latitude,
            "weather_longitude": self.longitude,
            "alert_endpoint": self.alert_endpoint,
            "roles_list": self.roles_list,
        }

    # =======================================================
    # SAVE LOGIC
    # =======================================================
    def _save(self):
        roles = self._collect_roles()

        self.node.config.update({
            "alert_to_role": self.alert_to_role.text().strip(),
            "zip_code": self.zip_code.text().strip(),
            "weather_latitude": self.latitude.text().strip(),
            "weather_longitude": self.longitude.text().strip(),
            "alert_endpoint": self.alert_endpoint.text().strip(),
            "service-manager": [{"role": roles}],
        })

        self.node.mark_dirty()
        self.accept()
