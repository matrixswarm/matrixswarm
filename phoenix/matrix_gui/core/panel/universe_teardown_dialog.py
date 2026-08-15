import time
import uuid

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log


class UniverseTeardownDialog(QDialog):
    """Confirm and dispatch a session-transport universe teardown."""

    def __init__(self, session_id, bus, deployment=None, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.bus = bus
        self.deployment = deployment or {}

        self.setWindowTitle("Destroy Remote Universe")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel("Destroy the active remote universe?")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        layout.addWidget(title)

        universe_label = (
            self.deployment.get("universe")
            or self.deployment.get("name")
            or "the universe currently hosting this session"
        )
        scope = QLabel(
            f"Matrix will level {universe_label} using the session's "
            "active transport. Choose which remote swarm files should also "
            "be removed."
        )
        scope.setTextFormat(Qt.TextFormat.PlainText)
        scope.setWordWrap(True)
        layout.addWidget(scope)

        self.delete_directive_checkbox = QCheckBox(
            "Delete the remote encrypted directive and matching swarm key, if present"
        )
        self.delete_directive_checkbox.setChecked(True)
        self.delete_directive_checkbox.toggled.connect(
            self._sync_cleanup_option
        )
        layout.addWidget(self.delete_directive_checkbox)

        self.cleanup_checkbox = QCheckBox(
            "Remove the corresponding runtime and static universe trees"
        )
        self.cleanup_checkbox.setChecked(True)
        layout.addWidget(self.cleanup_checkbox)

        retained = QLabel(
            "The Phoenix vault deployment is retained. You can deploy it "
            "again later to recreate the remote universe."
        )
        retained.setWordWrap(True)
        retained.setStyleSheet(
            "color: #9cf7e2; background: #102927; border: 1px solid #1abda8; "
            "border-radius: 5px; padding: 9px;"
        )
        layout.addWidget(retained)

        self.acknowledge_checkbox = QCheckBox(
            "I understand this stops the entire remote universe"
        )
        self.acknowledge_checkbox.toggled.connect(self._set_destroy_enabled)
        layout.addWidget(self.acknowledge_checkbox)

        buttons = QHBoxLayout()
        buttons.addStretch(1)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)

        self.destroy_button = QPushButton("Destroy Remote Universe")
        self.destroy_button.setEnabled(False)
        self.destroy_button.setDefault(False)
        self.destroy_button.setAutoDefault(False)
        self.destroy_button.setStyleSheet(
            "QPushButton { color: #ffd7d7; border: 1px solid #a94d55; "
            "padding: 7px 12px; } "
            "QPushButton:hover { background: #4a2026; } "
            "QPushButton:disabled { color: #696969; border-color: #444; }"
        )
        self.destroy_button.clicked.connect(self.deploy)
        buttons.addWidget(self.destroy_button)
        layout.addLayout(buttons)

    def _sync_cleanup_option(self, directive_selected):
        """Full-tree cleanup is valid only with directive/key deletion."""
        self.cleanup_checkbox.setEnabled(bool(directive_selected))
        if not directive_selected:
            self.cleanup_checkbox.setChecked(False)

    def _set_destroy_enabled(self, acknowledged):
        self.destroy_button.setEnabled(bool(acknowledged))

    def deploy(self):
        try:
            if not self.acknowledge_checkbox.isChecked():
                QMessageBox.warning(
                    self,
                    "Confirmation Required",
                    "Confirm that you understand the remote universe will stop.",
                )
                return

            packet = Packet()
            packet.set_data({
                "handler": "cmd_matrix_reloaded",
                "content": {
                    "delete_directive_with_key": (
                        self.delete_directive_checkbox.isChecked()
                    ),
                    "clean_up": self.cleanup_checkbox.isChecked(),
                    "confirm_response": 1,
                    "session_id": self.session_id,
                    "token": str(uuid.uuid4()),
                },
                "ts": time.time(),
            })

            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=packet,
            )
            self.accept()

        except Exception as exc:
            emit_gui_exception_log("UniverseTeardownDialog.deploy", exc)
            QMessageBox.warning(
                self,
                "Teardown Failed",
                f"Could not send the universe teardown command: {exc}",
            )