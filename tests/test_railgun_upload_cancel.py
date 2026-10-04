"""Synthetic SSH stream cancellation; never connects to a server."""
import os
import sys
import unittest
import base64
import json
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QCloseEvent
from matrix_gui.modules.railgun import remote_shell
from matrix_gui.modules.railgun import control_worker
from matrix_gui.swarm_workspace.cls_lib.deployment.dialog import railgun


class UploadCancellationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def worker(self):
        return railgun.RailgunWorker({}, {}, "synthetic", {
            "universe": "test", "linux_user": "matrix-test"})

    def test_cancel_before_connect_has_no_remote_effect(self):
        worker = self.worker()
        errors = []
        worker.sig_error.connect(errors.append)
        worker.cancel()
        with patch.object(railgun, "connect_ssh_profile") as connect:
            worker.run()
        connect.assert_not_called()
        self.assertIn("No remote boot command", errors[0])

    def test_deploy_and_session_restart_stream_only_saved_bundle_without_file_reads(self):
        bundle = {field: base64.b64encode(b"synthetic sealed bytes").decode()
                  for field in ("ciphertext", "nonce", "tag")}
        key = base64.b64encode(b"x" * 32).decode()
        for action in ("deploy", "restart"):
            with self.subTest(action=action):
                client, channel = Mock(), Mock()
                client.get_transport.return_value.open_session.return_value = channel
                channel.recv_ready.return_value = False
                channel.recv_stderr_ready.return_value = False
                channel.exit_status_ready.return_value = True
                channel.recv_exit_status.return_value = 0
                payload = bytearray()
                def send(chunk):
                    payload.extend(chunk)
                    return len(chunk)
                channel.send.side_effect = send
                module = railgun if action == "deploy" else control_worker
                if action == "deploy":
                    worker = railgun.RailgunWorker({}, bundle, key, {
                        "universe": "test", "linux_user": "matrix-test"})
                else:
                    worker = control_worker.ControlSessionWorker({}, "synthetic restart", action, bundle, key)
                with patch.object(module, "connect_ssh_profile", return_value=(client, "synthetic")), \
                        patch.object(module, "verify_remote_matrixd_stdin"), \
                        patch("builtins.open", side_effect=AssertionError("No local files may be read")), \
                        patch.object(Path, "open", side_effect=AssertionError("No local files may be read")):
                    worker.run()
                self.assertEqual({"version": 1, "encrypted_bundle": bundle, "swarm_key": key},
                                 json.loads(payload))
                channel.shutdown_write.assert_called_once()
                client.open_sftp.assert_not_called()
                if action == "restart":
                    self.assertIsNone(worker.error)
                    self.assertEqual((client, channel), worker.result)
                    channel.close()
                    client.close()

    def test_cancel_mid_upload_closes_transport_and_reports_unknown(self):
        worker = self.worker()
        client, channel = Mock(), Mock()
        client.get_transport.return_value.open_session.return_value = channel
        def send(chunk):
            worker.cancel()
            return min(10, len(chunk))
        channel.send.side_effect = send
        errors, done = [], []
        worker.sig_error.connect(errors.append)
        worker.sig_done.connect(done.append)
        with patch.object(railgun, "connect_ssh_profile", return_value=(client, "synthetic")), patch.object(railgun, "verify_remote_matrixd_stdin"), patch.object(remote_shell, "encode_boot_envelope", return_value=b"x" * 100):
            worker.run()
        channel.send.assert_called_once()
        channel.shutdown_write.assert_not_called()
        channel.close.assert_called_once()
        client.close.assert_called_once()
        self.assertFalse(done)
        self.assertIn("Remote outcome unknown", errors[0])
        channel.exec_command.assert_called_once()

    def test_zero_byte_send_fails_and_partial_sends_complete(self):
        channel = Mock()
        channel.send.return_value = 0
        with patch.object(remote_shell, "encode_boot_envelope", return_value=b"1234"):
            with self.assertRaises(ConnectionError):
                remote_shell.send_boot_envelope(channel, {}, "", check_cancel=lambda: None)
            channel.shutdown_write.assert_not_called()
            channel.send.return_value = 2
            self.assertEqual(4, remote_shell.send_boot_envelope(channel, {}, "", check_cancel=lambda: None))
            channel.shutdown_write.assert_called_once()

    def test_stalled_upload_has_deadline(self):
        channel = Mock()
        with patch.object(remote_shell, "encode_boot_envelope", return_value=b"1234"), patch("time.monotonic", side_effect=[0, 61]):
            with self.assertRaises(TimeoutError):
                remote_shell.send_boot_envelope(channel, {}, "", check_cancel=lambda: None)
        channel.send.assert_not_called()
        channel.shutdown_write.assert_not_called()

    def test_disconnect_does_not_retry_or_report_remote_success(self):
        for phase in ("connect", "dispatch", "upload", "lost-status"):
            with self.subTest(phase=phase):
                worker = self.worker()
                client, channel = Mock(), Mock()
                client.get_transport.return_value.open_session.return_value = channel
                channel.recv_ready.return_value = False
                channel.recv_stderr_ready.return_value = False
                channel.exit_status_ready.return_value = True
                channel.recv_exit_status.return_value = -1
                errors, done = [], []
                worker.sig_error.connect(errors.append)
                worker.sig_done.connect(done.append)
                if phase == "dispatch":
                    channel.exec_command.side_effect = EOFError("SECRET-MARKER")
                with patch.object(railgun, "connect_ssh_profile", return_value=(client, "synthetic")) as connect, patch.object(railgun, "verify_remote_matrixd_stdin"), patch.object(railgun, "send_boot_envelope", return_value=123) as send:
                    if phase == "connect":
                        connect.side_effect = EOFError("SECRET-MARKER")
                    if phase == "upload":
                        send.side_effect = EOFError("SECRET-MARKER")
                    worker.run()
                    if phase == "lost-status":
                        worker.run()
                    connect.assert_called_once()
                    self.assertLessEqual(channel.exec_command.call_count, 1)
                    self.assertLessEqual(send.call_count, 1)
                self.assertFalse(done)
                self.assertEqual(len(errors), 2 if phase == "lost-status" else 1)
                self.assertNotIn("SECRET-MARKER", errors[0])
                self.assertIn("No remote boot command" if phase == "connect" else "Remote outcome unknown", errors[0])

    def test_same_worker_is_one_attempt_even_after_connect_failure(self):
        worker = self.worker()
        with patch.object(railgun, "connect_ssh_profile", side_effect=EOFError("synthetic")) as connect:
            worker.run()
            worker.run()
            connect.assert_called_once()

    def test_dialog_stays_alive_during_cancel_without_waiting(self):
        with patch.object(railgun.RailgunWorker, "start"):
            dialog = railgun.RailgunDialog(None, {}, {}, "synthetic", {})
        dialog.show()
        with patch.object(dialog.worker, "isRunning", return_value=True), patch.object(dialog.worker, "wait") as wait:
            dialog.reject()
            dialog.done(0)
            event = QCloseEvent()
            dialog.closeEvent(event)
            self.assertFalse(event.isAccepted())
            self.assertTrue(dialog.isVisible())
            self.assertTrue(dialog.worker._cancel.is_set())
            wait.assert_not_called()
        dialog.reject()
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
