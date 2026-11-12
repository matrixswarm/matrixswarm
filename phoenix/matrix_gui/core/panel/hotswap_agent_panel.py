import base64, hashlib, time, copy, uuid
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6 import sip
from PyQt6.QtWidgets import QDialog, QMessageBox
from matrix_gui.core.dialog.hotswap_agent_dialog import HotswapAgentDialog
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.vault.embedded_source_update import bundle_fingerprint

_live_embedded_workers = set()


class EmbeddedSourceWorker(QThread):
    result = pyqtSignal(bool, str)

    def __init__(self, vault, uid, source, sha, fingerprint):
        super().__init__()
        self.vault, self.uid, self.source, self.sha, self.fingerprint = vault, uid, source, sha, fingerprint

    def run(self):
        try:
            if not self.vault.update_embedded_source(self.uid, self.source, self.sha, self.fingerprint):
                raise RuntimeError("The vault did not confirm the source update.")
            self.result.emit(True, "Embedded source saved for the next deployment. The running universe is unchanged. "
                                   "The target must validate and run this source when deployed. "
                                   "Reopen this session before saving another embedded-source change.")
        except Exception as exc:
            self.result.emit(False, str(exc))

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
        self._pending_token = None
        self._current_challenge = None
        self._embedded_worker = None
        self._pending_timer = QTimer(self)
        self._pending_timer.setSingleShot(True)
        self._pending_timer.timeout.connect(self._hotswap_timeout)
        self._chunk_timer = QTimer(self)
        self._chunk_timer.setSingleShot(True)
        self._chunk_timer.timeout.connect(self._retry_chunk)
        self._chunk_queue = []
        self._chunk_inflight = None
        self._chunk_attempts = 0
        self.tree = tree
        self.clear_to_show = True

        self.bus.on(
            f"inbound.verified.hotswap_agent.confirm",
            self._handle_confirm
        )
        self.bus.on("inbound.verified.hotswap_agent.error", self._handle_confirm)
        self.bus.on("inbound.verified.hotswap_agent.ack", self._handle_chunk_ack)
        self.bus.on("inbound.verified.hotswap_agent.challenge", self._handle_challenge)

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
            if self._embedded_worker is not None and self._embedded_worker.isRunning():
                QMessageBox.information(self.parent, "Save Embedded Source", "A vault save is already in progress.")
                return
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
        if sip.isdeleted(self):
            return
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
                limit = 16 * 1024 * 1024 if self._dlg.action == "save_embedded" else 524288
                code = f.read(limit + 1)
                if not code or len(code) > limit:
                    raise ValueError(f"Source must be between 1 byte and {limit} bytes for this action.")
                encoded = base64.b64encode(code).decode("utf-8")
                file_hash = hashlib.sha256(code).hexdigest()

            if self._dlg.action == "save_embedded":
                self._save_embedded_source(uid, encoded, file_hash)
                return

            token = uuid.uuid4().hex
            self._pending_token = token
            count = (len(code) + 8191) // 8192
            common = {"target_universal_id": uid, "session_id": self.session_id, "token": token,
                      "size": len(code), "count": count, "sha256": file_hash}
            self._chunk_queue = [{"handler": "cmd_hotswap_challenge", "timestamp": time.time(),
                                  "content": dict(common)}]

            if len(code) <= 8192:
                self._chunk_queue.append({"handler": "cmd_hotswap_agent", "timestamp": time.time(),
                    "content": {**common, "source_payload": {"payload": encoded, "sha256": file_hash},
                                "meta": meta, "restart": True}})
            else:
                self._chunk_queue.extend([
                    {"handler": "cmd_hotswap_transfer", "timestamp": time.time(),
                     "content": {**common, "kind": "chunk", "index": index,
                                 "data": base64.b64encode(code[index * 8192:(index + 1) * 8192]).decode("ascii")}}
                    for index in range(count)])
                self._chunk_queue.append({"handler": "cmd_hotswap_transfer", "timestamp": time.time(),
                                          "content": {**common, "kind": "commit"}})
            self._pending_timer.start(3900000)
            self._notify_progress("Sending boot-scoped source; restart confirmation can take several minutes.")
            self._send_next_chunk()

        except Exception as e:
            emit_gui_exception_log("HotswapAgentPanel._on_finished", e)
            QMessageBox.warning(self.parent, "Error", f"Hotswap failed: {e}")
            self._cleanup()

    def _handle_confirm(self, session_id, channel, source, payload, ts):
        """Toast + feed entry on success or failure."""
        if sip.isdeleted(self):
            return
        content = payload.get("content", {}) if isinstance(payload, dict) else {}
        if (session_id != self.session_id or not self._pending_token
                or not isinstance(content, dict) or content.get("token") != self._pending_token):
            return
        if self._current_challenge is not None:
            if content.get("challenge") != self._current_challenge:
                return
        elif self._chunk_inflight is None or self._chunk_inflight.get("handler") != "cmd_hotswap_challenge":
            return
        try:
            agent = content.get("target_universal_id", "unknown")
            sha = (content.get("sha256") or "")[:12]
            message = content.get("message", "")
            success = content.get("status") == "success"

            if self.conn:
                event = {
                    "event_type": "hotswap",
                    "agent": agent,
                    "sha": sha,
                    "details": message,
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

            if success and self.conn:
                self.conn.send({"type": "ui_toast", "session_id": self.session_id,
                                "message": message or f"{agent} hotswapped for this boot."})
            elif success:
                QMessageBox.information(self.parent, "Hotswap", message or f"{agent} hotswapped for this boot.")
            elif not success:
                QMessageBox.warning(self.parent, "Hotswap", message or "Hotswap could not be confirmed.")

        except Exception as e:
            emit_gui_exception_log("HotswapAgentPanel._handle_confirm", e)
        finally:
            self._cleanup()

    def _hotswap_timeout(self):
        if sip.isdeleted(self):
            return
        if self._pending_token:
            self._cleanup()
            QMessageBox.warning(self.parent, "Hotswap", "No confirmation arrived. Check the agent logs before retrying.")

    def _send_next_chunk(self):
        if sip.isdeleted(self):
            return
        if not self._pending_token or not self._chunk_queue:
            self._chunk_timer.stop()
            return
        self._chunk_inflight = self._chunk_queue.pop(0)
        self._chunk_attempts = 0
        self._send_inflight()

    def _send_inflight(self):
        if sip.isdeleted(self):
            return
        if not self._pending_token or self._chunk_inflight is None:
            return
        try:
            data = dict(self._chunk_inflight, timestamp=time.time())
            current = self._chunk_inflight
            self._chunk_attempts += 1
            packet = Packet()
            packet.set_data(data)
            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=packet, security_sig=True)
            if data["handler"] in ("cmd_hotswap_challenge", "cmd_hotswap_transfer") and self._chunk_inflight is current:
                # Email ingress/egress can each poll every 10–20 seconds.
                self._chunk_timer.start(30000)
            elif data["handler"] not in ("cmd_hotswap_challenge", "cmd_hotswap_transfer"):
                self._chunk_inflight = None
        except Exception as exc:
            self._cleanup()
            QMessageBox.warning(self.parent, "Hotswap", f"Could not send the source: {exc}")

    def _retry_chunk(self):
        if sip.isdeleted(self):
            return
        if self._chunk_inflight is None or not self._pending_token:
            return
        if self._chunk_attempts >= 3:
            self._cleanup()
            QMessageBox.warning(self.parent, "Hotswap", "A source chunk was not acknowledged. The transfer may be incomplete; check the agent before retrying.")
            return
        self._send_inflight()

    def _handle_chunk_ack(self, session_id, channel, source, payload, ts):
        if sip.isdeleted(self):
            return
        if (session_id != self.session_id or not self._pending_token or self._chunk_inflight is None
                or self._chunk_inflight.get("handler") != "cmd_hotswap_transfer"):
            return
        ack = payload.get("content", {}) if isinstance(payload, dict) else {}
        expected = self._chunk_inflight.get("content", {})
        if (not isinstance(ack, dict) or ack.get("token") != self._pending_token
                or any(ack.get(key) != expected.get(key) for key in
                       ("target_universal_id", "sha256", "count", "kind", "index", "challenge"))):
            return
        self._chunk_timer.stop()
        if expected.get("kind") == "chunk" and (expected.get("index", 0) + 1) % 8 == 0:
            self._notify_progress(f"Source transfer: {expected['index'] + 1} of {expected['count']} chunks acknowledged.")
        if expected.get("kind") == "commit":
            self._notify_progress("Source delivered; waiting for the new agent to start.")
        self._chunk_inflight = None
        self._chunk_attempts = 0
        if self._chunk_queue:
            self._send_next_chunk()

    def _handle_challenge(self, session_id, channel, source, payload, ts):
        if sip.isdeleted(self):
            return
        if (session_id != self.session_id or not self._pending_token or self._chunk_inflight is None
                or self._chunk_inflight.get("handler") != "cmd_hotswap_challenge"):
            return
        reply = payload.get("content", {}) if isinstance(payload, dict) else {}
        expected = self._chunk_inflight.get("content", {})
        if (not isinstance(reply, dict) or reply.get("token") != self._pending_token
                or any(reply.get(key) != expected.get(key) for key in
                       ("session_id", "target_universal_id", "sha256", "size", "count"))):
            return
        challenge = reply.get("challenge")
        if not isinstance(challenge, str) or len(challenge) != 64 or any(c not in "0123456789abcdef" for c in challenge):
            return
        self._current_challenge = challenge
        self._chunk_timer.stop()
        for packet in self._chunk_queue:
            packet["content"]["challenge"] = challenge
        self._chunk_inflight = None
        self._chunk_attempts = 0
        if self._chunk_queue:
            self._send_next_chunk()

    def _save_embedded_source(self, uid, encoded, source_hash):
        vault = getattr(self.parent, "vault_singleton", None)
        bundle = self.deployment.get("encrypted_bundle")
        if vault is None or not isinstance(bundle, dict):
            raise RuntimeError("The saved deployment or unlocked vault is unavailable. Reopen the session and try again.")
        fingerprint = bundle_fingerprint(bundle)
        worker = EmbeddedSourceWorker(vault, uid, encoded, source_hash, fingerprint)
        self._embedded_worker = worker
        _live_embedded_workers.add(worker)
        worker.result.connect(self._embedded_save_result)
        worker.finished.connect(self._embedded_save_finished)
        worker.finished.connect(lambda: _live_embedded_workers.discard(worker))
        worker.finished.connect(worker.deleteLater)
        self._cleanup()
        self._notify_progress("Saving embedded source for the next deployment…")
        worker.start()

    def _notify_progress(self, message):
        if sip.isdeleted(self):
            return
        if self.conn:
            try:
                self.conn.send({"type": "ui_toast", "session_id": self.session_id, "message": message})
            except Exception as exc:
                emit_gui_exception_log("HotswapAgentPanel._notify_progress", exc)

    def _embedded_save_result(self, success, message):
        if sip.isdeleted(self):
            return
        if success:
            QMessageBox.information(self.parent, "Save Embedded Source", message)
        else:
            QMessageBox.warning(self.parent, "Save Embedded Source", message)

    def _embedded_save_finished(self):
        if sip.isdeleted(self):
            return
        self._embedded_worker = None

    def _cleanup(self):
        """Clear dialog and internal flags."""
        if sip.isdeleted(self):
            return
        self.clear_to_show=True
        self._pending_token = None
        self._current_challenge = None
        self._pending_timer.stop()
        self._chunk_timer.stop()
        self._chunk_queue = []
        self._chunk_inflight = None
        self._chunk_attempts = 0
        if self._dlg:
            self._dlg.deleteLater()
            self._dlg = None
