"""Phoenix editor for the opt-in MCP Reflex signed integration probe."""

from PyQt6.QtWidgets import QCheckBox, QLabel, QLineEdit, QMessageBox

from .base_editor import BaseEditor


class McpReflexProbe(BaseEditor):
    def _build_form(self):
        cfg = self.config
        self.layout.addRow(QLabel("🧪 Signed MCP Airlock Probe"))
        self.run_on_boot = QCheckBox("Run one integration probe after boot")
        self.run_on_boot.setChecked(cfg.get("run_on_boot", False) is True)
        self.server_id = QLineEdit(str(cfg.get("server_id", "smoke")))
        self.message = QLineEdit(str(cfg.get("message", "Airlock is tight")))
        self.layout.addRow(self.run_on_boot)
        self.layout.addRow("Server ID:", self.server_id)
        self.layout.addRow("Echo message:", self.message)

    def _save(self):
        server_id = self.server_id.text().strip()
        message = self.message.text().strip()
        if not server_id or not message:
            QMessageBox.warning(
                self,
                "Probe config not saved",
                "Server ID and echo message are required.",
            )
            return
        self.node.config.update({
            "run_on_boot": self.run_on_boot.isChecked(),
            "server_id": server_id,
            "message": message,
        })
        self.node.mark_dirty()
        self.accept()
