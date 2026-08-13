from .base_editor import BaseEditor
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QListWidget, QComboBox,
    QPushButton, QInputDialog, QLabel, QLineEdit, QFormLayout, QCheckBox
)

class Sora(BaseEditor):
    def _build_form(self):
        cfg = self.config

        # =======================================================
        # --- CORE SETTINGS SECTION ---
        # =======================================================
        core_box = QWidget()
        core_layout = QFormLayout(core_box)
        core_layout.setContentsMargins(0, 0, 0, 0)
        core_layout.setSpacing(4)

        # Model Dropdown
        self.model = QComboBox()
        self.model.addItems([
            "sora-2",
            "sora-2-pro",
            "sora-2-2025-10-06",
            "sora-2-pro-2025-10-06",
            "sora-2-2025-12-08"
        ])
        self.model.setCurrentText(cfg.get("model", "sora-2"))
        self.layout.addRow("Model:", self.model)

        # Resolution
        self.res = QComboBox()
        self.res.addItems(["720x1280", "1280x720", "1024x1792", "1792x1024"])
        self.res.setCurrentText(cfg.get("resolution", "1280x720"))
        core_layout.addRow("Resolution:", self.res)

        # Watermark on final frame
        self.watermark_enabled = QCheckBox("Enable watermark")
        self.watermark_enabled.setChecked(bool(cfg.get("watermark_enabled", False)))
        self.watermark_text = QLineEdit(cfg.get("water_mark_text", ""))
        core_layout.addRow(self.watermark_enabled)
        core_layout.addRow(self.watermark_text)

        # Duration (seconds)
        self.duration = QLineEdit(str(cfg.get("duration", 30)))
        self.layout.addRow("Default Duration (sec):", self.duration)

        # Poll Interval
        self.poll = QLineEdit(str(cfg.get("poll_interval", 60)))
        core_layout.addRow("Poll Interval (sec):", self.poll)

        # Output paths
        self.video_path = QLineEdit(cfg.get("video_output_path", "/matrix/videos"))
        self.thumb_path = QLineEdit(cfg.get("thumbnail_output_path", "/matrix/thumbs"))
        core_layout.addRow("Video Output Path:", self.video_path)
        core_layout.addRow("Thumbnail Path:", self.thumb_path)

        self.layout.addRow(QLabel("🎬 Sora Core Configuration"))
        self.layout.addRow(core_box)

        # =======================================================
        # --- SERVICE MANAGER ROLES SECTION ---
        # =======================================================
        self.layout.addRow(QLabel("🔗 Service Manager Roles"))
        self._build_roles_section(cfg)

        # Store widgets for save
        self.inputs = {
            "model": self.model,
            "resolution": self.res,
            "poll_interval": self.poll,
            "video_output_path": self.video_path,
            "thumbnail_output_path": self.thumb_path,
            "roles_list": self.roles_list,
        }

    # =======================================================
    # ROLES SECTION
    # =======================================================
    def _build_roles_section(self, cfg):
        svc_mgr = cfg.get("service-manager", [])
        if svc_mgr and isinstance(svc_mgr, list):
            roles = svc_mgr[0].get("role", [])
        else:
            roles = []

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.roles_list = QListWidget()
        for r in roles:
            self.roles_list.addItem(r)
        layout.addWidget(self.roles_list)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        add_btn = QPushButton("+")
        rm_btn = QPushButton("–")
        clr_btn = QPushButton("Clear")

        btn_row.addWidget(add_btn)
        btn_row.addWidget(rm_btn)
        btn_row.addWidget(clr_btn)
        layout.addLayout(btn_row)

        add_btn.clicked.connect(self._add_role)
        rm_btn.clicked.connect(self._remove_role)
        clr_btn.clicked.connect(self._clear_roles)

        self.layout.addRow("Roles:", container)

    # =======================================================
    # BUTTON HELPERS
    # =======================================================
    def _add_role(self):
        text, ok = QInputDialog.getText(
            self, "Add Role",
            "Enter role (example: hive.sora.render@cmd_msg_prompt):"
        )
        if ok and text.strip():
            self.roles_list.addItem(text.strip())

    def _remove_role(self):
        for item in self.roles_list.selectedItems():
            self.roles_list.takeItem(self.roles_list.row(item))

    def _clear_roles(self):
        self.roles_list.clear()

    # =======================================================
    # SAVE LOGIC
    # =======================================================
    def _save(self):
        roles = [self.roles_list.item(i).text() for i in range(self.roles_list.count())]

        self.node.config.update({
            "model": self.model.currentText(),
            "duration": int(self.duration.text()),
            "resolution": self.res.currentText(),
            "poll_interval": int(self.poll.text()),
            "video_output_path": self.video_path.text(),
            "thumbnail_output_path": self.thumb_path.text(),
            "watermark_enabled": self.watermark_enabled.isChecked(),
            "water_mark_text": self.watermark_text.text().strip(),
            "service-manager": [{"role": roles}],
        })

        self.node.mark_dirty()
        self.accept()