"""The hotswap UI must distinguish live and saved-directive actions."""
import base64
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))
from PyQt6.QtWidgets import QApplication, QDialog
from matrix_gui.core.panel.hotswap_agent_panel import HotswapAgentPanel, EmbeddedSourceWorker


class HotswapPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / "agent.py"
        self.source.write_text("print('ok')\n")
        self.bus = Mock()
        self.panel = HotswapAgentPanel("session", self.bus, None, {}, parent=None)
        self.dialog = SimpleNamespace(file_path=str(self.source), meta={}, action="hotswap",
                                      agent_dropdown=SimpleNamespace(currentText=lambda: "target"),
                                      deleteLater=Mock())
        self.panel._dlg = self.dialog

    def accept_challenge(self):
        request = dict(self.panel._chunk_inflight["content"])
        self.panel._handle_challenge("session", "", "", {"content": {**request, "challenge": "b" * 64}}, 0)

    def test_live_request_has_reply_token_and_ignores_other_sessions(self):
        self.panel._on_finished(QDialog.DialogCode.Accepted)
        self.assertTrue(self.panel._pending_timer.isActive())
        self.assertEqual(self.bus.emit.call_args.kwargs["packet"].get_packet()["handler"], "cmd_hotswap_challenge")
        self.accept_challenge()
        request = self.bus.emit.call_args.kwargs["packet"].get_packet()
        content = request["content"]
        self.assertEqual(content["session_id"], "session")
        self.assertTrue(content["token"])
        self.assertEqual(content["source_payload"]["sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        with patch("matrix_gui.core.panel.hotswap_agent_panel.QMessageBox.information") as info:
            self.panel._handle_confirm("other", "", "", {"content": {"token": content["token"], "status": "success"}}, 0)
            self.panel._handle_confirm("session", "", "", {"content": {"token": content["token"], "status": "success", "challenge": "c" * 64}}, 0)
            info.assert_not_called()
            self.assertEqual(self.panel._pending_token, content["token"])

    def test_error_response_is_not_reported_as_success(self):
        self.panel._pending_token = "token"
        self.panel._current_challenge = "b" * 64
        with patch("matrix_gui.core.panel.hotswap_agent_panel.QMessageBox.warning") as warning, \
             patch("matrix_gui.core.panel.hotswap_agent_panel.QMessageBox.information") as info:
            self.panel._handle_confirm("session", "", "", {"content": {"token": "token", "status": "error", "message": "failed", "challenge": "b" * 64}}, 0)
        warning.assert_called_once()
        info.assert_not_called()

    def test_save_next_deploy_does_not_dispatch_live_command(self):
        self.dialog.action = "save_embedded"
        with patch.object(self.panel, "_save_embedded_source") as save:
            self.panel._on_finished(QDialog.DialogCode.Accepted)
        save.assert_called_once_with("target", base64.b64encode(self.source.read_bytes()).decode(),
                                     hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.bus.emit.assert_not_called()

    def test_large_source_is_sent_as_bounded_signed_chunks(self):
        self.source.write_bytes(b"x" * 40000)
        self.panel._on_finished(QDialog.DialogCode.Accepted)
        self.accept_challenge()
        while self.panel._chunk_inflight is not None:
            expected = self.panel._chunk_inflight["content"]
            self.panel._handle_chunk_ack("session", "", "", {"content": dict(expected)}, 0)
        calls = self.bus.emit.call_args_list
        packets = [call.kwargs["packet"].get_packet() for call in calls]
        self.assertEqual(len(packets), 7)
        self.assertTrue(all(call.kwargs["security_sig"] is True for call in calls))
        self.assertEqual(packets[0]["handler"], "cmd_hotswap_challenge")
        self.assertTrue(all(packet["handler"] == "cmd_hotswap_transfer" for packet in packets[1:]))
        self.assertTrue(all(len(packet["content"].get("data", "")) <= 10924 for packet in packets[1:]))
        self.assertEqual(packets[-1]["content"]["kind"], "commit")

    def test_lost_and_delayed_ack_retry_only_the_inflight_chunk(self):
        self.source.write_bytes(b"x" * 9000)
        self.panel._on_finished(QDialog.DialogCode.Accepted)
        self.accept_challenge()
        self.assertEqual(self.bus.emit.call_count, 2)
        first = dict(self.panel._chunk_inflight["content"])
        stale = dict(first, challenge="c" * 64)
        self.panel._handle_chunk_ack("session", "", "", {"content": stale}, 0)
        self.assertEqual(self.bus.emit.call_count, 2)  # ACK from another Matrix process ignored
        self.panel._retry_chunk()  # Simulate one lost acknowledgement.
        self.assertEqual(self.bus.emit.call_count, 3)
        self.panel._handle_chunk_ack("session", "", "", {"content": first}, 0)
        self.assertEqual(self.bus.emit.call_count, 4)
        second = dict(self.panel._chunk_inflight["content"])
        self.panel._handle_chunk_ack("session", "", "", {"content": first}, 0)
        self.assertEqual(self.bus.emit.call_count, 4)  # delayed duplicate ignored
        self.assertEqual(self.panel._chunk_inflight["content"], second)
        with patch("matrix_gui.core.panel.hotswap_agent_panel.QMessageBox.warning") as warning:
            self.panel._retry_chunk()
            self.panel._retry_chunk()
            self.panel._retry_chunk()
        warning.assert_called_once()
        self.assertIsNone(self.panel._pending_token)

    def test_slow_multi_chunk_session_has_sufficient_bound_and_progress(self):
        self.source.write_bytes(b"x" * (8 * 8192 + 1))
        self.panel.conn = Mock()
        self.panel._on_finished(QDialog.DialogCode.Accepted)
        self.assertEqual(self.panel._pending_timer.interval(), 3900000)
        self.assertEqual(self.panel._chunk_timer.interval(), 30000)
        self.accept_challenge()
        while self.panel._chunk_inflight is not None:
            ack = dict(self.panel._chunk_inflight["content"])
            self.panel._handle_chunk_ack("session", "", "", {"content": ack}, 0)
        messages = [call.args[0].get("message", "") for call in self.panel.conn.send.call_args_list]
        self.assertTrue(any("8 of 9 chunks acknowledged" in message for message in messages))
        self.assertTrue(any("waiting for the new agent" in message for message in messages))

    def test_chunk_fits_real_signed_encrypted_wss_and_ssh_envelopes(self):
        from Crypto.PublicKey import RSA
        from matrix_gui.core.class_lib.packet_delivery.utility.security.packet_security import wrap_packet_securely
        sys.path.insert(0, str(ROOT / "matrixos"))
        from core.python_core.class_lib.packet_delivery.utility.security.packet_size import guard_packet_size
        key = RSA.generate(2048)
        signing = {"pubkey": key.publickey().export_key().decode(), "remote_privkey": key.export_key().decode()}
        deployment = {"agents": [{"name": "matrix", "universal_id": "matrix"}],
                      "certs": {"matrix": {"signing": signing}, "ssh": {"signing": signing}}}
        self.source.write_bytes(b"x" * 9000)
        self.panel._on_finished(QDialog.DialogCode.Accepted)
        self.accept_challenge()
        chunk = self.bus.emit.call_args.kwargs["packet"].get_packet()
        inner = wrap_packet_securely(chunk, deployment, sign=True, encrypt=True).get_packet()
        envelope = {"matrix_packet": inner, "ts": 1234567890}
        self.assertTrue(guard_packet_size(envelope, log=lambda *_: None))
        ssh = wrap_packet_securely(envelope, deployment, sign=True, encrypt=True, target_uid="ssh").get_packet()
        self.assertTrue(guard_packet_size(ssh, log=lambda *_: None))

    def test_saved_source_worker_reports_vault_failure(self):
        vault = SimpleNamespace(update_embedded_source=Mock(side_effect=RuntimeError("read-only")))
        worker = EmbeddedSourceWorker(vault, "target", "source", "hash", "fingerprint")
        results = []
        worker.result.connect(lambda ok, message: results.append((ok, message)))
        worker.run()
        self.assertEqual(results, [(False, "read-only")])

    def test_destroyed_parent_cancels_timer_and_late_worker_is_safe(self):
        script = textwrap.dedent('''
            import os, sys, threading, time
            from PyQt6 import sip
            from PyQt6.QtWidgets import QApplication, QWidget
            from matrix_gui.core.panel.hotswap_agent_panel import HotswapAgentPanel, _live_embedded_workers
            app = QApplication([])
            gate = threading.Event()
            class Vault:
                def update_embedded_source(self, *args):
                    if not gate.wait(3): raise RuntimeError("worker stalled")
                    return True
            class Bus:
                def on(self, *args): pass
            parent = QWidget()
            parent.vault_singleton = Vault()
            panel = HotswapAgentPanel("session", Bus(), None, {"encrypted_bundle": {}}, parent=parent)
            panel._save_embedded_source("target", "source", "hash")
            timer = panel._pending_timer
            panel._pending_token = "token"
            timer.start(10)
            sip.delete(parent)
            assert sip.isdeleted(panel) and sip.isdeleted(timer)
            # The Python event bus can retain bound callbacks even after Qt
            # has destroyed the underlying panel and timer.
            panel._handle_confirm("session", "", "", {"content": {"token": "token", "status": "error"}}, 0)
            panel._handle_chunk_ack("session", "", "", {"content": {}}, 0)
            panel._hotswap_timeout()
            panel._embedded_save_result(False, "late")
            gate.set()
            deadline = time.monotonic() + 5
            while _live_embedded_workers and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
            assert not _live_embedded_workers
        ''')
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "phoenix"), env.get("PYTHONPATH", "")])
        result = subprocess.run([sys.executable, "-B", "-c", script], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                encoding="utf-8", errors="replace", timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
