# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import time, copy
from PyQt6.QtCore import QObject

from matrix_gui.core.dialog.restart_agent_dialog import RestartAgentDialog
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class RestartAgentPanel(QObject):
    """Wrapper around :class:`RestartAgentDialog` with feed / toast plumbing."""
    def __init__(self, session_id, bus, conn, deployment, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.bus = bus
        self.conn = conn
        self.deployment = copy.deepcopy(deployment)
        self.parent = parent
        self._dlg = None

        #only show one dialog at a time
        self.clear_to_show = True

        # Listen for restart confirmation from Matrix → Phoenix
        self.bus.on(
            f"inbound.verified.restart_dialog.result",
            self._handle_result
        )

    def launch(self, uid: str = None):
        """Open the dialog and optionally pre-populate the *Target UID* field."""
        try:

            if not self.clear_to_show:
                return

            self.clear_to_show = False

            self._dlg = RestartAgentDialog(
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
            emit_gui_exception_log("RestartAgentPanel.launch", e)

    def _on_finished(self, result):
        """Runs when user cancels or after *Restart* is clicked."""
        if result != self._dlg.DialogCode.Accepted:
            self._cleanup()
        self.clear_to_show=True

    def _handle_result(self, session_id, channel, source, payload, ts):
        """
        Receive **restart_dialog.result** and broadcast UI feedback.

        Emits an info/error toast and a structured swarm-feed entry.
        """
        try:

            content = payload.get("content", {})
            uid = content.get("universal_id", "unknown")
            stage = content.get("stage", "?")
            result = content.get("result", {})
            success = result.get("success", False)
            err = result.get("error")

            if success:
                msg = f"Agent '{uid}' restarted successfully (stage: {stage})"
            else:
                msg = f"⚠️ Restart failed for '{uid}': {err}"

            # Send toast event up to cockpit
            if self.conn:
                self.conn.send({
                    "type": "ui_toast",
                    "session_id": self.session_id,
                    "message": msg
                })

            # Optionally append to Swarm Feed
            if self.conn:
                event = {
                    "event_type": "restart",
                    "agent": uid,
                    "stage": stage,
                    "details": msg,
                    "session_id": self.session_id,
                    "deployment": self.deployment.get("label", "unknown"),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "level": "INFO" if success else "ERROR"
                }
                self.conn.send({
                    "type": "swarm_feed",
                    "session_id": self.session_id,
                    "event": event
                })

        except Exception as e:
            emit_gui_exception_log("RestartAgentPanel._handle_result", e)
        finally:
            self._cleanup()

    def _cleanup(self):
        """Delete the dialog and clear internal references."""
        self.clear_to_show = True
        if self._dlg:
            self._dlg.deleteLater()
            self._dlg = None
