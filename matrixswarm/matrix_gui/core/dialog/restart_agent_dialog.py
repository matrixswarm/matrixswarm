# Authored by Daniel F MacDonald and ChatGPT 5 aka The Generals
import time, uuid
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QMessageBox
)
from PyQt5.QtCore import QTimer
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class RestartAgentDialog(QDialog):
    def __init__(self, session_id, bus, conn, deployment=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔁 Restart Agent")
        self.resize(400, 150)
        self.conn=conn
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
        self.agent_id = self.agent_edit.text().strip()
        if not self.agent_id:
            QMessageBox.warning(self, "Error", "Enter a valid agent universal_id.")
            return

        confirm = QMessageBox.question(
            self, "Confirm Restart",
            f"Are you sure you want to restart '{self.agent_id}' and its subtree?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            # Build shutdown + resume payloads
            shutdown = {
                "handler": "cmd_shutdown_subtree",
                "content": {"universal_id": self.agent_id},
                "ts": time.time()
            }
            resume = {
                "handler": "cmd_resume_subtree",
                "content": {"universal_id": self.agent_id},
                "ts": time.time()
            }

            # Emit shutdown immediately
            pk1 = Packet(); pk1.set_data(shutdown)
            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=pk1)

            # Schedule resume a second later
            QTimer.singleShot(1000, lambda: self._emit_resume(resume))

            self.accept()

        except Exception as e:
            emit_gui_exception_log("RestartAgentDialog.deploy", e)
            QMessageBox.warning(self, "Error", f"Restart failed: {e}")

    def _emit_resume(self, resume):
        pk2 = Packet(); pk2.set_data(resume)
        self.bus.emit("outbound.message", session_id=self.session_id,
                      channel="outgoing.command", packet=pk2)
