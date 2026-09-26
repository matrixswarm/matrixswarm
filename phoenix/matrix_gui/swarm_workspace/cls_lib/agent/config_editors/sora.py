from .base_editor import BaseEditor
from .mixin.service_roles_mixin import ServiceRolesMixin
from PyQt6.QtWidgets import (
    QWidget, QComboBox,
    QInputDialog, QLabel, QLineEdit, QFormLayout, QCheckBox, QMessageBox
)

class Sora(BaseEditor, ServiceRolesMixin):
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
        self._select_saved_choice(self.model, cfg.get("model", "sora-2"))
        self.layout.addRow("Model:", self.model)

        # Resolution
        self.res = QComboBox()
        self.res.addItems(["720x1280", "1280x720", "1024x1792", "1792x1024"])
        self._select_saved_choice(self.res, cfg.get("resolution", "1280x720"))
        core_layout.addRow("Resolution:", self.res)

        # Watermark on final frame
        self.watermark_enabled = QCheckBox("Enable watermark")
        self._load_saved_bool(self.watermark_enabled, cfg.get("watermark_enabled", False))
        self.watermark_text = QLineEdit()
        self._load_saved_text(self.watermark_text, cfg.get("water_mark_text", ""))
        core_layout.addRow(self.watermark_enabled)
        core_layout.addRow(self.watermark_text)

        # Duration (seconds)
        self.duration = QLineEdit(str(cfg.get("duration", 30)))
        self.layout.addRow("Default Duration (sec):", self.duration)

        # Poll Interval
        self.poll = QLineEdit(str(cfg.get("poll_interval", 60)))
        core_layout.addRow("Poll Interval (sec):", self.poll)

        # Output paths
        self.video_path = QLineEdit()
        self._load_saved_text(self.video_path, cfg.get("video_output_path", "/matrix/videos"))
        self.thumb_path = QLineEdit()
        self._load_saved_text(self.thumb_path, cfg.get("thumbnail_output_path", "/matrix/thumbs"))
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
        return ServiceRolesMixin._build_roles_section(self, cfg)

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

        try:
            watermark_enabled = self._saved_bool(self.watermark_enabled, "Enable watermark")
            watermark_text = self._saved_text(self.watermark_text, "Watermark text")
            video_path = self._saved_text(self.video_path, "Video output path")
            thumb_path = self._saved_text(self.thumb_path, "Thumbnail output path")
            model = self._saved_choice(self.model, "Model")
            resolution = self._saved_choice(self.res, "Resolution")
            duration = int(self.duration.text())
            poll_interval = int(self.poll.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Configuration",
                                f"Check the configuration values before saving.\n{exc}")
            return

        self.node.config.update({
            "model": model,
            "duration": duration,
            "resolution": resolution,
            "poll_interval": poll_interval,
            "video_output_path": video_path,
            "thumbnail_output_path": thumb_path,
            "watermark_enabled": watermark_enabled,
            "water_mark_text": watermark_text.strip(),
            "service-manager": self._service_manager_with_roles(roles),
        })

        self.node.mark_dirty()
        self.accept()
