import base64, hashlib, time, copy
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QDialog, QMessageBox
from matrix_gui.core.dialog.hotswap_agent_dialog import HotswapAgentDialog
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class HotswapAgentPanel(QObject):
    """
    Panel that streams a compiled agent file to a running target agent and
    restarts it atomically (hot-swap).

    Notes
    -----
    • Provides a *running-agents* dropdown sourced from the current tree
    • Emits **cmd_hotswap_agent** with encoded payload
    • Handles **hotswap_agent.confirm** for user feedback.
    """
    def __init__(self, session_id, bus, conn, deployment, parent=None, tree=None):
        super().__init__(parent)
        self.session_id = session_id
        self.bus = bus
        self.conn = conn
        self.deployment = copy.deepcopy(deployment)
        self.parent = parent
        self._dlg = None
        self.tree = tree
        self.clear_to_show = True

        self.bus.on(
            f"inbound.verified.hotswap_agent.confirm",
            self._handle_confirm
        )

    def _collect_running_agent_ids(self, tree_data):
        try:
            uids = []

            def walk(node):
                if not isinstance(node, dict):
                    return
                uid = node.get("universal_id")
                if uid:
                    uids.append(uid)
                for child in node.get("children", []):
                    walk(child)

            walk(tree_data)
            return uids
        except Exception as e:
            emit_gui_exception_log("SessionWindow._collect_running_agent_ids", e)
            return []


    def launch(self, tree_data, uid: str = None):
        """Open dialog; supply current tree so the dropdown is populated."""
        try:
            if not self.clear_to_show:
                return

            self.clear_to_show = False

            running_agents=self._collect_running_agent_ids(tree_data)
            self._dlg = HotswapAgentDialog(self.session_id, self.bus, running_agents, parent=self.parent)
            if uid:
                self._dlg.agent_dropdown.setCurrentText(uid)

            self._dlg.finished.connect(self._on_finished)
            self._dlg.show()
        except Exception as e:
            emit_gui_exception_log("HotswapAgentPanel.launch", e)

    def _on_finished(self, result):
        """Validate inputs, build packet, emit over bus."""
        if result != QDialog.DialogCode.Accepted:
            self._cleanup()
            return
        file_path = self._dlg.file_path
        meta = self._dlg.meta or {}
        uid = self._dlg.agent_dropdown.currentText()

        if not file_path or not uid:
            QMessageBox.warning(self.parent, "Error", "Select a valid agent and file.")
            self._cleanup()
            return

        try:
            with open(file_path, "rb") as f:
                code = f.read()
                encoded = base64.b64encode(code).decode("utf-8")
                file_hash = hashlib.sha256(code).hexdigest()


            payload = {
                "handler": "cmd_hotswap_agent",
                "timestamp": time.time(),
                "content": {
                    "target_universal_id": uid,
                    "source_payload": {
                        "payload": encoded,
                        "sha256": file_hash
                    },
                    "meta": meta,
                    "update_tree": False,
                    "update_source": True,
                    "restart": True,
                    "return_handler": "hotswap_agent.confirm"
                }
            }

            pk = Packet()
            pk.set_data(payload)
            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=pk)

        except Exception as e:
            emit_gui_exception_log("HotswapAgentPanel._on_finished", e)
            QMessageBox.warning(self.parent, "Error", f"Hotswap failed: {e}")
            self._cleanup()

    def _handle_confirm(self, session_id, channel, source, payload, ts):
        """Toast + feed entry on success or failure."""
        try:
            content = payload.get("content", {})
            agent = content.get("target_universal_id", "unknown")
            sha = content.get("sha256", "")[:12]
            message = content.get("message", "")

            if self.conn:
                event = {
                    "event_type": "hotswap",
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
                "message": f"{agent} hotswapped successfully!"
            })

        except Exception as e:
            emit_gui_exception_log("HotswapAgentPanel._handle_confirm", e)
        finally:
            self._cleanup()

    def _cleanup(self):
        """Clear dialog and internal flags."""
        self.clear_to_show=True
        if self._dlg:
            self._dlg.deleteLater()
            self._dlg = None
