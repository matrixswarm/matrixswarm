from .base_editor import BaseEditor
from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QSpinBox, QFormLayout, QGroupBox
)
from .mixin.service_roles_mixin import ServiceRolesMixin


class MetaBlast(BaseEditor, ServiceRolesMixin):
    """
    Config Editor for meta_blast agent.
    Mirrors CdnDozer style, but exposes:
      - poll_interval
      - batch_limit
      - owner_id
      - object_type
      - oracle.{agent_name, method, timeout}
    """

    def _build_form(self):
        cfg = self.config or {}
        oracle_cfg = cfg.get("oracle", {})

        # ============================================
        # META_BLAST CORE SETTINGS
        # ============================================
        core_box = QWidget()
        core_layout = QFormLayout(core_box)
        core_layout.setContentsMargins(0, 0, 0, 0)
        core_layout.setSpacing(6)

        self.poll_interval = QSpinBox()
        self.poll_interval.setRange(1, 3600)
        self.poll_interval.setValue(int(cfg.get("poll_interval", 20)))

        self.batch_limit = QSpinBox()
        self.batch_limit.setRange(1, 100)
        self.batch_limit.setValue(int(cfg.get("batch_limit", 3)))

        self.owner_id = QSpinBox()
        self.owner_id.setRange(1, 999999)
        self.owner_id.setValue(int(cfg.get("owner_id", 3)))

        self.object_type = QSpinBox()
        self.object_type.setRange(1, 999999)
        self.object_type.setValue(int(cfg.get("object_type", 3333)))

        core_layout.addRow("Polling Interval (sec):", self.poll_interval)
        core_layout.addRow("Batch Limit:", self.batch_limit)
        core_layout.addRow("Owner ID:", self.owner_id)
        core_layout.addRow("Object Type (tag_to_object):", self.object_type)

        self.layout.addRow(QLabel("🧠 MetaBlast Core Settings"))
        self.layout.addRow(core_box)

        # ============================================
        # ORACLE SETTINGS
        # ============================================
        oracle_box = QWidget()
        oracle_layout = QFormLayout(oracle_box)
        oracle_layout.setContentsMargins(0, 0, 0, 0)
        oracle_layout.setSpacing(6)

        self.oracle_role = QLineEdit(oracle_cfg.get("oracle_role", "hive.oracle"))
        self.oracle_method = QLineEdit(oracle_cfg.get("method", "metadata"))

        self.oracle_timeout = QSpinBox()
        self.oracle_timeout.setRange(1, 600)
        self.oracle_timeout.setValue(int(oracle_cfg.get("timeout", 60)))

        oracle_layout.addRow("Oracle Agent Name:", self.oracle_role)
        oracle_layout.addRow("Oracle Method:", self.oracle_method)
        oracle_layout.addRow("Oracle Timeout (sec):", self.oracle_timeout)

        self.layout.addRow(QLabel("🔮 Oracle Metadata Generator"))
        self.layout.addRow(oracle_box)

        # ============================================
        # ROLE SECTION (same as Dozer)
        # ============================================
        self.layout.addRow(QLabel("🔗 Service Manager Roles"))
        self._build_roles_section(cfg, default_role="srv.meta_blast@cmd_meta")

        # ============================================
        # PERSISTENT INPUTS
        # ============================================
        self.inputs = {
            "poll_interval": self.poll_interval,
            "batch_limit": self.batch_limit,
            "owner_id": self.owner_id,
            "object_type": self.object_type,

            "oracle_role": self.oracle_role,
            "oracle_method": self.oracle_method,
            "oracle_timeout": self.oracle_timeout,

            "roles_list": self.roles_list,
        }

    # ============================================
    # SAVE LOGIC
    # ============================================
    def _save(self):
        roles = self._collect_roles()

        self.node.config.update({
            "poll_interval": int(self.poll_interval.value()),
            "batch_limit": int(self.batch_limit.value()),
            "owner_id": int(self.owner_id.value()),
            "object_type": int(self.object_type.value()),

            "oracle": {
                "oracle_role": self.oracle_role.text().strip(),
                "method": self.oracle_method.text().strip(),
                "timeout": int(self.oracle_timeout.value()),
            },

            "service-manager": [{"role": roles}],
        })

        self.node.mark_dirty()
        self.accept()
