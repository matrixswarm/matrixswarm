# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import uuid, base64, hashlib, time, copy
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtWidgets import QDialog
from matrix_gui.core.dialog.replace_agent_dialog import ReplaceAgentDialog
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class ReplaceAgentPanel(QObject):
    """
    Lets an operator hot-replace an agent’s on-disk source file.

    The panel collects a ``.py`` file, base64-encodes it, attaches a SHA-256
    and emits **cmd_replace_source** to Matrix. Success is confirmed via
    **replace_agent_source.confirm**.
    """
    def __init__(self, session_id, bus, conn, deployment, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.bus = bus
        self.conn = conn
        self.deployment = copy.deepcopy(deployment)
        self.parent = parent
        self._dlg = None
        # Listen for server confirmation
        self.bus.on(
            f"inbound.verified.replace_agent_source.confirm",
            self._handle_confirm
        )

    def launch(self):
        """Display the *ReplaceAgentDialog* file picker."""
        try:
            self._dlg = ReplaceAgentDialog(parent=self.parent)

            self._dlg.finished.connect(self._on_finished)
            self._dlg.show()
        except Exception as e:
            emit_gui_exception_log("ReplaceAgentPanel.launch", e)

    def _on_finished(self, result):
        """If accepted, read file → encode → emit outbound packet."""
        if result != QDialog.DialogCode.Accepted:
            self._cleanup()
            return

        file_path, agent_name = self._dlg.get_selection()
        if not file_path or not agent_name:
            QMessageBox.warning(self.parent, "Error", "Select a valid agent source file first.")
            self._cleanup()
            return

        try:
            with open(file_path, "rb") as f:
                code = f.read()
                encoded = base64.b64encode(code).decode("utf-8")
                file_hash = hashlib.sha256(code).hexdigest()

            token = str(uuid.uuid4())

            payload = {
                "handler": "cmd_replace_source",
                "ts": time.time(),
                "content": {
                    "target_agent_name": agent_name,
                    "payload": {
                        "session_id": self.session_id,
                        "token": token,
                        "source": encoded,
                        "sha256": file_hash,
                        "return_handler": "replace_agent_source.confirm"
                    }
                }
            }

            pk = Packet()
            pk.set_data(payload)
            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=pk, security_sig=True)



        except Exception as e:
            emit_gui_exception_log("ReplaceAgentPanel._on_finished", e)
            QMessageBox.warning(self.parent, "Error", f"Deployment failed: {e}")
            self._cleanup()

    def _handle_confirm(self, session_id, channel, source, payload, ts):
        """Handle Matrix confirmation and surface a toast + feed entry."""
        try:
            content = payload.get("content", {})
            agent = content.get("target_agent_name", "unknown")
            sha = content.get("sha256", "")[:12]
            message = content.get("message", "")

            if self.conn:
                event = {
                    "event_type": "replace",
                    "agent": agent,
                    "sha": sha,
                    "details": message,
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

            self.conn.send({
                "type": "ui_toast",
                "session_id": self.session_id,
                "message": f"{agent} replaced successfully!"
            })

        except Exception as e:
            emit_gui_exception_log("ReplaceAgentPanel._handle_confirm", e)
        finally:
            self._cleanup()

    def _cleanup(self):
        """Free dialog resources and reset state."""
        self.clear_to_show = True
        if self._dlg:
            self._dlg.deleteLater()
            self._dlg = None