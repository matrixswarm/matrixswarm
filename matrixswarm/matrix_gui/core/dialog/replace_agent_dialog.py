# Authored by Daniel F MacDonald and ChatGPT 5 aka The Generals
import os, uuid, base64, hashlib, time, re, ast, json, ast
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QMessageBox
)
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log


class ReplaceAgentDialog(QDialog):
    def __init__(self, session_id, bus, conn, deployment, parent=None):
        super().__init__(parent)
        self.setWindowTitle("♻️ Replace Agent Source")
        self.resize(400, 150)
        self.deployment=deployment
        self.conn = conn
        self.session_id = session_id
        self.active_log_token = None
        self.bus = bus
        self.file_path = None
        self.agent_name = None

        layout = QVBoxLayout(self)

        # File picker
        self.file_label = QLabel("No file selected")
        btn_pick = QPushButton("📂 Select Agent Source")
        btn_pick.clicked.connect(self.pick_file)

        row1 = QHBoxLayout()
        row1.addWidget(self.file_label)
        row1.addWidget(btn_pick)
        layout.addLayout(row1)
        self.openQbox=None

        # Buttons
        row2 = QHBoxLayout()
        btn_ok = QPushButton("Deploy")
        btn_ok.clicked.connect(self.deploy)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        row2.addWidget(btn_ok)
        row2.addWidget(btn_cancel)
        layout.addLayout(row2)

        if self.bus:
            self.bus.on(
                f"inbound.verified.replace_agent_source.confirm.{self.session_id}",
                self._handle_source_update
            )

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Agent Source", "", "Python (*.py);;All Files (*)")
        if not path:
            return
        self.file_path = path
        self.file_label.setText(os.path.basename(path))
        # infer agent name from filename or directory
        self.agent_name = os.path.splitext(os.path.basename(path))[0]

    def deploy(self):
        if not self.file_path or not self.agent_name:
            QMessageBox.warning(self, "Error", "Select a valid agent source file first.")
            return

        try:
            with open(self.file_path, "rb") as f:
                code = f.read()
                encoded = base64.b64encode(code).decode("utf-8")
                file_hash = hashlib.sha256(code).hexdigest()

            self.active_log_token = str(uuid.uuid4())

            payload = {
                "handler": "cmd_replace_source",
                "ts": time.time(),
                "content": {
                    "target_agent_name": self.agent_name,
                    "payload": {
                        "session_id": self.session_id,
                        "token": self.active_log_token,
                        "source": encoded,
                        "sha256": file_hash,
                        "return_handler": "replace_agent_source.confirm"
                    }
                }
            }

            pk = Packet()
            pk.set_data(payload)
            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=pk)

        except Exception as e:
            emit_gui_exception_log("ReplaceAgentDialog.deploy", e)
            QMessageBox.warning(self, "Error", f"Deployment failed: {e}")

    def _handle_source_update(self, session_id, channel, source, payload, ts):
        content = payload.get("content", {})
        agent = content.get("target_agent_name", "unknown")
        status = content.get("status", "n/a")
        sha = content.get("sha256", "")[:12]
        message = content.get("message", "")
        trace = content.get("token")

        if self.conn:
            event = {
                "event_type": "replace",
                "agent": agent,
                "status": status,
                "sha": sha,
                "details": message,
                "trace": trace,
                "session_id": self.session_id,
                "deployment": self.deployment.get("label", "unknown"),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "level": "INFO"
            }
            self.conn.send({
                "type": "swarm_feed",
                "session_id": self.session_id,
                "event": event
            })