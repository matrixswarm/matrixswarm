# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import time, copy
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QDialog
from matrix_gui.core.dialog.delete_agent_dialog import DeleteAgentDialog
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class DeleteAgentPanel(QObject):
    """
    Presenter object that wraps :class:`DeleteAgentDialog`.

    Responsibilities
    ----------------
    • Ensures only one dialog is open at a time
    • Emits *cmd_delete_agent* over the Matrix bus
    • Listens for **delete_agent.confirm** to toast the UI and feed
      the cockpit swarm-feed panel.
    """
    def __init__(self, session_id, bus, conn, deployment, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.bus = bus
        self.conn = conn
        self.deployment = copy.deepcopy(deployment)
        self.parent = parent
        self.clear_to_show = True
        self._dlg = None

        # Listen for confirmation from Matrix → Phoenix
        self.bus.on(
            f"inbound.verified.delete_agent.confirm",
            self._handle_confirm
        )

    def launch(self, uid: str = None):
        """
        Show the dialog, optionally pre-filling ``uid``.

        Parameters
        ----------
        uid :
            Universal-ID of the agent that should be highlighted when
            the dialog appears.
        """
        try:

            if not self.clear_to_show:
                return

            self.clear_to_show = False

            self._dlg = DeleteAgentDialog(
                session_id=self.session_id,
                bus=self.bus,
                conn=self.conn,
                deployment=self.deployment,
                parent=self.parent
            )
            if uid:
                self._dlg.prefill_uid(uid)
            self._dlg.finished.connect(self._on_finished)
            self._dlg.show()
        except Exception as e:
            emit_gui_exception_log("DeleteAgentPanel.launch", e)

    def _on_finished(self, result):
        """Dialog closed."""
        if result != QDialog.DialogCode.Accepted:
            self._cleanup()
        self.clear_to_show = True

    def _handle_confirm(self, session_id, channel, source, payload, ts):
        """
        Bus callback for **delete_agent.confirm**.

        Converts the wire payload into a cockpit toast + swarm-feed event.
        """
        try:
            content = payload.get("content", {})
            result = content.get("result", {})
            success = bool(result.get("success", False))
            msg = result.get("error") or content.get("message", "")
            target = content.get("universal_id") or content.get("details", {}).get("target_universal_id", "?")
            kill_list = content.get("details", {}).get("kill_list", [])
            trace = content.get("response_id")

            level = "INFO" if success else "ERROR"
            status = "success" if success else "failed"

            if self.conn:
                event = {
                    "event_type": "delete",
                    "agent": target,
                    "status": status,
                    "kill_list": kill_list,
                    "details": msg,
                    "trace": trace,
                    "session_id": self.session_id,
                    "deployment": self.deployment.get("label", "unknown"),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "level": level
                }
                self.conn.send({
                    "type": "swarm_feed",
                    "session_id": self.session_id,
                    "event": event
                })
                self.conn.send({
                    "type": "ui_toast",
                    "session_id": self.session_id,
                    "message": f"{target} deleted successfully!" if success
                    else f"⚠️ Delete failed for {target}: {msg}"
                })
        except Exception as e:
            emit_gui_exception_log("DeleteAgentPanel._handle_confirm", e)
        finally:
            self._cleanup()

    def _cleanup(self):
        """Ensure dialog and signals are cleaned up."""
        self.clear_to_show=True
        if self._dlg:
            self._dlg.deleteLater()
            self._dlg = None
