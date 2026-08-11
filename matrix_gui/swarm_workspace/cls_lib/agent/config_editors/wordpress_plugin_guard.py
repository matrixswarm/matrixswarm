from .base_editor import BaseEditor
from .mixin.service_roles_mixin import ServiceRolesMixin

from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit,
    QCheckBox, QSpinBox, QFormLayout
)


class WordpressPluginGuard(BaseEditor, ServiceRolesMixin):
    """
    WordPress Plugin Guard configuration editor.

    Keeps the agent from falling back to BaseEditor and exposes the
    routing fields needed for swarm alerts / RPC panel replies.
    """

    def _build_form(self):
        cfg = self.config

        # =======================================================
        # General Settings
        # =======================================================
        general_box = QWidget()
        general_layout = QFormLayout(general_box)
        general_layout.setContentsMargins(0, 0, 0, 0)
        general_layout.setSpacing(4)

        self.plugin_dir = QLineEdit(
            cfg.get("plugin_dir", "/var/www/html/wp-content/plugins")
        )

        self.snapshot_root = QLineEdit(
            cfg.get("snapshot_root", "/opt/swarm/guard/snapshots")
        )

        self.quarantine_dir = QLineEdit(
            cfg.get("quarantine_dir", "/opt/quarantine/wp_plugins")
        )

        self.site_id = QLineEdit(
            cfg.get("site_id", "site1")
        )

        self.interval = QSpinBox()
        self.interval.setRange(1, 86400)
        self.interval.setValue(int(cfg.get("interval", 30)))

        self.enforce = QCheckBox("Enforce quarantine")
        self.enforce.setChecked(bool(cfg.get("enforce", False)))

        self.block_new = QCheckBox("Block new/untracked plugins")
        self.block_new.setChecked(bool(cfg.get("block_new", False)))

        self.read_only = QCheckBox("Read only / no writes")
        self.read_only.setChecked(bool(cfg.get("read_only", False)))

        general_layout.addRow("Plugin Directory:", self.plugin_dir)
        general_layout.addRow("Snapshot Root:", self.snapshot_root)
        general_layout.addRow("Quarantine Root:", self.quarantine_dir)
        general_layout.addRow("Site ID:", self.site_id)
        general_layout.addRow("Scan Interval (sec):", self.interval)
        general_layout.addRow(self.enforce)
        general_layout.addRow(self.block_new)
        general_layout.addRow(self.read_only)

        self.layout.addRow(QLabel("🧩 WordPress Plugin Guard"))
        self.layout.addRow(general_box)

        # =======================================================
        # Alert / RPC Routing
        # =======================================================
        routing_box = QWidget()
        routing_layout = QFormLayout(routing_box)
        routing_layout.setContentsMargins(0, 0, 0, 0)
        routing_layout.setSpacing(4)

        self.alert_to_role = QLineEdit(
            cfg.get("alert_to_role", "hive.alert")
        )

        self.report_to_role = QLineEdit(
            cfg.get("report_to_role", "")
        )

        self.rpc_router_role = QLineEdit(
            cfg.get("rpc_router_role", "hive.rpc")
        )

        routing_layout.addRow("Alert To Role:", self.alert_to_role)
        routing_layout.addRow("Report To Role:", self.report_to_role)
        routing_layout.addRow("RPC Router Role:", self.rpc_router_role)

        self.layout.addRow(QLabel("📡 Alert / RPC Routing"))
        self.layout.addRow(routing_box)

        # =======================================================
        # Service Manager Roles
        # =======================================================
        self.layout.addRow(QLabel("🔗 Service Manager Roles"))

        default_roles = [
            "wordpress_plugin_guard.status@cmd_list_alert_status",
            "wordpress_plugin_guard.list_plugins@cmd_list_plugins",
            "wordpress_plugin_guard.snapshot_plugins@cmd_snapshot_plugins",
            "wordpress_plugin_guard.snapshot_plugin@cmd_snapshot_plugin",
            "wordpress_plugin_guard.snapshot_untracked@cmd_snapshot_untracked",
            "wordpress_plugin_guard.disapprove_plugin@cmd_disapprove_plugin",
            "wordpress_plugin_guard.enforce@cmd_enforce",
            "wordpress_plugin_guard.block@cmd_toggle_block",
            "wordpress_plugin_guard.quarantine@cmd_quarantine_plugin",
            "wordpress_plugin_guard.restore@cmd_restore_plugin",
            "wordpress_plugin_guard.delete_quarantined@cmd_delete_quarantined_plugin",
        ]

        cfg.setdefault("service-manager", [{"role": default_roles}])
        self._build_roles_section(cfg)

    def _save(self):
        roles = self._collect_roles()

        self.node.config.update({
            "plugin_dir": self.plugin_dir.text().strip(),
            "snapshot_root": self.snapshot_root.text().strip(),
            "quarantine_dir": self.quarantine_dir.text().strip(),
            "site_id": self.site_id.text().strip() or "site1",
            "interval": int(self.interval.value()),
            "enforce": self.enforce.isChecked(),
            "block_new": self.block_new.isChecked(),
            "read_only": self.read_only.isChecked(),

            # routing
            "alert_to_role": self.alert_to_role.text().strip() or "hive.alert",
            "report_to_role": self.report_to_role.text().strip(),
            "rpc_router_role": self.rpc_router_role.text().strip() or "hive.rpc",

            # service-manager
            "service-manager": [{
                "role": roles,
                "scope": ["parent", "any"],
                "priority": {
                    "hive.log.delivery": -1,
                    "hive.proxy.route": 5,
                    "default": 10
                }
            }],
        })

        self.node.mark_dirty()
        self.accept()