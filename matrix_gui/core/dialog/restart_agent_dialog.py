import time, uuid
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QMessageBox, QCheckBox
)
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class RestartAgentDialog(QDialog):
    def __init__(self, session_id, bus, conn, deployment=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔁 Restart Agent")
        self.resize(400, 180)
        self.conn = conn
        self.session_id = session_id
        self.bus = bus
        self.agent_id = None

        layout = QVBoxLayout(self)

        # Target agent field
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Target Agent UID:"))
        self.agent_edit = QLineEdit()
        row1.addWidget(self.agent_edit)
        layout.addLayout(row1)

        # Restart full subtree checkbox
        self.full_subtree_checkbox = QCheckBox("Restart full subtree (all descendants)")
        layout.addWidget(self.full_subtree_checkbox)

        # Buttons
        row2 = QHBoxLayout()
        btn_ok = QPushButton("Restart")
        btn_ok.clicked.connect(self.deploy)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        row2.addWidget(btn_ok)
        row2.addWidget(btn_cancel)
        layout.addLayout(row2)

    def prefill_uid(self, uid: str):
        """Allow tree/context menu to pre-populate target agent."""
        self.agent_edit.setText(uid)
        self.agent_id = uid

    def deploy(self):

        try:

            self.agent_id = self.agent_edit.text().strip()
            if not self.agent_id:
                QMessageBox.warning(self, "Error", "Enter a valid agent universal_id.")
                return

            full_subtree = self.full_subtree_checkbox.isChecked()

            confirm = QMessageBox.question(
                self, "Confirm Restart",
                f"Are you sure you want to restart '{self.agent_id}'"
                + (" and its full subtree?" if full_subtree else " only?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

            restart_packet = Packet()
            restart_packet.set_data({
                "handler": "cmd_restart_subtree",
                "content": {
                    "target_universal_id": self.agent_id,
                    "restart_full_subtree": full_subtree,
                    "session_id": self.session_id,
                    "token": str(uuid.uuid4()),
                    "confirm_response": 1,
                    "return_handler": "restart_dialog.result"
                },
                "ts": time.time()
            })

            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=restart_packet)
            self.accept()

        except Exception as e:
            emit_gui_exception_log("RestartAgentDialog.deploy", e)
            QMessageBox.warning(self, "Error", f"Restart failed: {e}")
