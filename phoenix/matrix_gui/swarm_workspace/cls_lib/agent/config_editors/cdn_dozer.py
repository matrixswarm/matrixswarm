from .base_editor import BaseEditor
from PyQt6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QSpinBox, QFormLayout
)
from .mixin.service_roles_mixin import ServiceRolesMixin


class CdnDozer(BaseEditor, ServiceRolesMixin):
    """
    Minimal Dozer config editor.
    NOTE: SSH host/user/key/password should come from node constraints
    (do NOT expose them here).
    """

    def _build_form(self):
        cfg = self.config or {}

        # -----------------------------
        # Remote path (where Dozer places files on CDN)
        # -----------------------------
        rc_box = QWidget()
        rc_layout = QFormLayout(rc_box)
        rc_layout.setContentsMargins(0, 0, 0, 0)
        rc_layout.setSpacing(6)

        # remote path key kept as 'ssh_path' to match agent expectations
        self.remote_path = QLineEdit(cfg.get("ssh_path", ""))
        rc_layout.addRow("Remote Path (ssh_path):", self.remote_path)

        self.layout.addRow(QLabel("🌐 CDN Path (no credentials here)"))
        self.layout.addRow(rc_box)

        # -----------------------------
        # Dozer Operation Section
        # -----------------------------
        ops_box = QWidget()
        ops_layout = QFormLayout(ops_box)
        ops_layout.setContentsMargins(0, 0, 0, 0)
        ops_layout.setSpacing(6)

        self.poll_interval = QSpinBox()
        self.poll_interval.setRange(1, 3600)
        self.poll_interval.setValue(int(cfg.get("poll_interval", 10)))

        self.watch_path = QLineEdit(cfg.get("watch_path", "/matrix/sora/outbox"))

        ops_layout.addRow("Polling Interval (sec):", self.poll_interval)
        ops_layout.addRow("Fallback Watch Path:", self.watch_path)

        self.layout.addRow(QLabel("⚙️ Dozer Operation Settings"))
        self.layout.addRow(ops_box)

        # -----------------------------
        # Service Manager Roles (same mixin you already use)
        # -----------------------------
        self.layout.addRow(QLabel("🔗 Service Manager Roles"))
        self._build_roles_section(cfg, default_role="cdn.dozer@cmd_dozer")

        # -----------------------------
        # Save Inputs (what will be persisted)
        # -----------------------------
        self.inputs = {
            "ssh_path": self.remote_path,
            "poll_interval": self.poll_interval,
            "watch_path": self.watch_path,
            "roles_list": self.roles_list,
        }

    # ---------------------------------------------------------
    # SAVE CONFIG
    # ---------------------------------------------------------
    def _save(self):
        roles = self._collect_roles()

        # update node config (no credentials here)
        self.node.config.update({
            "ssh_path": self.remote_path.text().strip(),
            "poll_interval": int(self.poll_interval.value()),
            "watch_path": self.watch_path.text().strip(),
            "service-manager": [{"role": roles}],
        })

        self.node.mark_dirty()
        self.accept()
