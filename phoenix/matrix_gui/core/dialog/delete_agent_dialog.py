# Authored by Daniel F MacDonald and ChatGPT 5 aka The Generals
import time, uuid
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QMessageBox
)
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class DeleteAgentDialog(QDialog):
    def __init__(self, session_id, bus, conn, deployment, parent=None):
        super().__init__(parent)
        self.setWindowTitle("☠️ Delete Agent")
        self.resize(400, 120)
        self.deployment = deployment
        self.conn = conn
        self.session_id = session_id
        self.bus = bus
        self.agent_id = None
        self.token = str(uuid.uuid4())

        layout = QVBoxLayout(self)


        # Input field for agent UID
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Target Agent UID:"))
        self.agent_edit = QLineEdit()
        row1.addWidget(self.agent_edit)
        layout.addLayout(row1)

        # Buttons
        row2 = QHBoxLayout()
        btn_ok = QPushButton("Delete")
        btn_ok.clicked.connect(self.deploy)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        row2.addWidget(btn_ok)
        row2.addWidget(btn_cancel)
        layout.addLayout(row2)

    def deploy(self):
        self.agent_id = self.agent_edit.text().strip()
        if not self.agent_id:
            QMessageBox.warning(self, "Error", "Enter a valid agent universal_id.")
            return
        try:
            payload = {
                "handler": "cmd_delete_agent",
                "ts": time.time(),
                "content": {
                    "target_universal_id": self.agent_id,
                    "confirm_response": True,
                    "session_id": self.session_id,
                    "return_handler": "delete_agent.confirm",
                    "token": self.token
                }
            }
            pk = Packet()
            pk.set_data(payload)
            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=pk)
            self.accept()
        except Exception as e:
            emit_gui_exception_log("DeleteAgentDialog.deploy", e)
            QMessageBox.warning(self, "Error", f"Delete command failed: {e}")

    def prefill_uid(self, uid: str):
        self.agent_edit.setText(uid)
        self.agent_id = uid