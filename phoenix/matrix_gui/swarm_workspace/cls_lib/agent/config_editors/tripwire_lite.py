from .base_editor import BaseEditor
from .mixin.service_roles_mixin import ServiceRolesMixin
from .mixin.list_editor_mixin import ListEditorMixin

from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit,
    QCheckBox, QSpinBox, QFormLayout
)

class TripwireLite(BaseEditor, ServiceRolesMixin, ListEditorMixin):
    """
    Tripwire Lite configuration editor
    Commander Edition — refactored with ListEditorMixin
    """
    def _build_form(self):
        cfg = self.config

        # =======================================================
        # --- GENERAL SETTINGS ---
        # =======================================================
        general_box = QWidget()
        general_layout = QFormLayout(general_box)
        general_layout.setContentsMargins(0, 0, 0, 0)
        general_layout.setSpacing(4)

        self.quarantine_root = QLineEdit(cfg.get("quarantine_root", "/matrix/quarantine"))

        self.interval = QSpinBox()
        self.interval.setRange(1, 3600)
        self.interval.setValue(int(cfg.get("interval", 5)))

        self.cooldown = QSpinBox()
        self.cooldown.setRange(0, 86400)
        self.cooldown.setValue(int(cfg.get("cooldown", 900)))

        self.dry_run = QCheckBox("Dry run (do not quarantine)")
        self.dry_run.setChecked(bool(cfg.get("dry_run", True)))

        self.enforce = QCheckBox("Enforce (actively quarantine)")
        self.enforce.setChecked(bool(cfg.get("enforce", False)))

        general_layout.addRow("Quarantine Root:", self.quarantine_root)
        general_layout.addRow("Scan Interval (sec):", self.interval)
        general_layout.addRow("Cooldown (sec):", self.cooldown)
        general_layout.addRow(self.dry_run)
        general_layout.addRow(self.enforce)

        self.layout.addRow(QLabel("🛡️ General Settings"))
        self.layout.addRow(general_box)

        # =======================================================
        # --- WATCH PATHS (list of dicts) ---
        # =======================================================
        self._build_list_section(
            label="👁️ Watch Paths",
            data=cfg.get("watch_paths", []),
            columns=["path", "recursive", "watch_dirs", "watch_files"],
            attr_name="watch_paths"
        )

        # =======================================================
        # --- IGNORE PATHS (simple list) ---
        # =======================================================
        ignore_data = [{"path": p} for p in cfg.get("ignore_paths", [])]
        self._build_list_section(
            label=" Ignore Paths",
            data=ignore_data,
            columns=["path"],
            attr_name="ignore_paths"
        )

        # =======================================================
        # --- ALLOWED EXTENSIONS (simple list) ---
        # =======================================================
        allowed_data = [{"extension": x} for x in cfg.get("allowed_extensions", [])]
        self._build_list_section(
            label=" Allowed Extensions",
            data=allowed_data,
            columns=["extension"],
            attr_name="allowed_extensions"
        )

        # =======================================================
        # --- SUSPICIOUS EXTENSIONS (simple list) ---
        # =======================================================
        suspicious_data = [{"extension": x} for x in cfg.get("suspicious_extensions", [])]
        self._build_list_section(
            label=" Suspicious Extensions",
            data=suspicious_data,
            columns=["extension"],
            attr_name="suspicious_extensions"
        )

        # =======================================================
        # --- ALERT ROUTING ---
        # =======================================================
        self.alert_to_role = QLineEdit(cfg.get("alert_to_role", "hive.alert"))

        self.layout.addRow(QLabel(" Alert Routing"))
        self.layout.addRow("Alert To Role:", self.alert_to_role)

        # =======================================================
        # --- SERVICE MANAGER ROLES ---
        # =======================================================
        self.layout.addRow(QLabel("🔗 Service Manager Roles"))
        self._build_roles_section(cfg, default_role="tripwire.guard.status@cmd_list_status")

    # =======================================================
    # SAVE LOGIC
    # =======================================================
    def _save(self):
        roles = self._collect_roles()

        # List editor returns list of dicts, so convert appropriately:

        # WATCH PATHS: list of dicts exactly matching expected structure
        watch_paths = self._collect_list_data("watch_paths")

        # IGNORE PATHS: collapse dict → list of strings
        ignore_paths = [x["path"] for x in self._collect_list_data("ignore_paths")]

        # Allowed + suspicious extensions
        allowed_extensions = [x["extension"] for x in self._collect_list_data("allowed_extensions")]
        suspicious_extensions = [x["extension"] for x in self._collect_list_data("suspicious_extensions")]

        self.node.config.update({
            "quarantine_root": self.quarantine_root.text().strip(),
            "interval": int(self.interval.value()),
            "cooldown": int(self.cooldown.value()),
            "dry_run": self.dry_run.isChecked(),
            "enforce": self.enforce.isChecked(),
            "watch_paths": watch_paths,
            "ignore_paths": ignore_paths,
            "allowed_extensions": allowed_extensions,
            "suspicious_extensions": suspicious_extensions,
            "alert_to_role": self.alert_to_role.text().strip(),
            "service-manager": [{"role": roles}],
        })

        self.node.mark_dirty()
        self.accept()
