"""Publish server-wide source using the deployment's pinned SSH identity."""
import copy
import time

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QDialog, QMessageBox

from matrix_gui.core.dialog.replace_agent_dialog import ReplaceAgentDialog
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.railgun.source_publish_worker import SourcePublishWorker, MAX_SOURCE_BYTES

_live_workers = set()  # QThreads survive destruction of the session panel.


class ReplaceAgentPanel(QObject):
    def __init__(self, session_id, bus, conn, deployment, parent=None, vault_connection=None):
        super().__init__(parent)
        self.session_id, self.bus, self.conn = session_id, bus, conn
        self.deployment = copy.deepcopy(deployment)
        self.parent = parent
        self.vault_connection = vault_connection
        self._dlg = None
        self._worker = None

    def launch(self):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self.parent, "Replace Source", "A source publication is already in progress.")
            return
        try:
            self._dlg = ReplaceAgentDialog(parent=self.parent)
            self._dlg.finished.connect(self._on_finished)
            self._dlg.show()
        except Exception as exc:
            emit_gui_exception_log("ReplaceAgentPanel.launch", exc)

    def _on_finished(self, result):
        if result != QDialog.DialogCode.Accepted:
            self._cleanup()
            return
        file_path, agent_name = self._dlg.get_selection()
        self._cleanup()
        if not file_path or not agent_name:
            QMessageBox.warning(self.parent, "Replace Source", "Select a valid agent source file first.")
            return
        try:
            serial = str(self.deployment.get("ssh_serial") or "")
            if not serial:
                raise ValueError("This deployment has no recorded administrative SSH profile")
            if self.vault_connection is None:
                raise ValueError("The session vault connection is unavailable")
            registry = self.vault_connection.fetch_fresh(target="registry")
            ssh = registry.get("ssh", {}) if isinstance(registry, dict) else {}
            profile = ssh.get(serial) if isinstance(ssh, dict) else None
            if not isinstance(profile, dict):
                raise ValueError("The deployment's recorded SSH profile is unavailable")
            recorded = self.deployment.get("railgun_target_identity")
            actual = {"host": str(profile.get("host", "")).strip().lower(),
                      "port": int(profile.get("port", 22)),
                      "pin": profile.get("trusted_host_fingerprint", "")}
            if not isinstance(recorded, dict) or actual != recorded or not actual["host"] or not actual["pin"]:
                raise ValueError("The recorded deployment target is missing or no longer matches its SSH profile")
            with open(file_path, "rb") as stream:
                source = stream.read(MAX_SOURCE_BYTES + 1)
            if not source or len(source) > MAX_SOURCE_BYTES:
                raise ValueError("Source must be between 1 byte and 4 MiB")
            worker = SourcePublishWorker(profile, agent_name, source)
            self._worker = worker
            _live_workers.add(worker)
            worker.result.connect(self._on_result)
            worker.finished.connect(self._on_worker_finished)
            worker.finished.connect(lambda: _live_workers.discard(worker))
            worker.finished.connect(worker.deleteLater)
            worker.start()
        except Exception as exc:
            emit_gui_exception_log("ReplaceAgentPanel._on_finished", exc)
            QMessageBox.warning(self.parent, "Replace Source", str(exc))

    def _on_worker_finished(self):
        self._worker = None

    def _on_result(self, result, error):
        if error:
            QMessageBox.warning(self.parent, "Replace Source", str(error))
            return
        agent, sha = result["agent"], result["sha256"]
        message = (f"{agent} source replaced on the server; running agents were not restarted. "
                   "Existing pinned hashes and clown-car embedded source copies are unchanged.")
        if self.conn:
            try:
                self.conn.send({"type": "swarm_feed", "session_id": self.session_id,
                    "event": {"event_type": "replace", "agent": agent, "sha": sha[:12],
                              "details": message, "session_id": self.session_id,
                              "deployment": self.deployment.get("label", "unknown"),
                              "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "level": "INFO"}})
                self.conn.send({"type": "ui_toast", "session_id": self.session_id, "message": message})
                return
            except Exception as exc:
                emit_gui_exception_log("ReplaceAgentPanel._on_result", exc)
        QMessageBox.information(self.parent, "Replace Source", message)

    def _cleanup(self):
        if self._dlg:
            self._dlg.deleteLater()
            self._dlg = None
