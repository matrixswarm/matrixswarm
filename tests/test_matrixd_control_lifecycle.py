"""Real offscreen control dialog, synthetic SSH streams; no server actions."""
import os
from pathlib import Path
import sys
import unittest
import threading
import time
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from PyQt6 import QtCore, QtWidgets
from matrix_gui.modules.directive.deploy_dialog import DeployDialog
from matrix_gui.modules.railgun.control_worker import ControlSessionWorker


class ControlLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.dialog = DeployDialog({}, deployment={"universe": "test"})
        self.addCleanup(self.dialog.deleteLater)
        self.channel = Mock()
        self.client = Mock()
        self.dialog._active_channel = self.channel
        self.dialog._ssh_client = self.client
        self.dialog._poll_timer = QtCore.QTimer(self.dialog)
        self.channel.recv_ready.return_value = False
        self.channel.recv_stderr_ready.return_value = False
        self.channel.exit_status_ready.return_value = False

    def test_continuous_output_is_bounded_and_both_streams_served(self):
        self.channel.recv_ready.return_value = True
        self.channel.recv_stderr_ready.return_value = True
        self.channel.recv.return_value = b"<b>literal stdout</b>"
        self.channel.recv_stderr.return_value = b"stderr"
        self.channel.exit_status_ready.return_value = True
        self.dialog._poll_ssh_channel()
        self.assertEqual(self.channel.recv.call_count, 16)
        self.assertEqual(self.channel.recv_stderr.call_count, 16)
        self.assertIn("<b>literal stdout</b>", self.dialog.output.toPlainText())
        self.channel.close.assert_not_called()
        self.channel.recv_ready.return_value = False
        self.channel.recv_stderr_ready.return_value = False
        self.channel.recv_exit_status.return_value = 0
        self.dialog._poll_ssh_channel()
        self.channel.close.assert_called_once()
        self.client.close.assert_called_once()

    def test_eof_breaks_read_loop(self):
        self.channel.recv_ready.return_value = True
        self.channel.recv.return_value = b""
        self.dialog._poll_ssh_channel()
        self.channel.recv.assert_called_once()

    def test_stream_exception_is_reported_without_secret_and_cleans_up(self):
        self.channel.recv_ready.side_effect = RuntimeError("SYNTHETIC-SECRET")
        with self.assertLogs("matrix_gui.util.exception_diagnostics", level="ERROR") as logs:
            self.dialog._poll_ssh_channel()
        self.assertIn("[UNKNOWN]", self.dialog.output.toPlainText())
        self.assertNotIn("SYNTHETIC-SECRET", self.dialog.output.toPlainText() + "\n".join(logs.output))
        self.channel.close.assert_called_once()
        self.client.close.assert_called_once()

    def test_reject_and_done_cleanup_are_idempotent(self):
        self.dialog._poll_timer.start(10000)
        self.dialog.reject()
        self.dialog.done(0)
        self.assertFalse(self.dialog._poll_timer.isActive())
        self.channel.close.assert_called_once()
        self.client.close.assert_called_once()

    def test_channel_close_failure_does_not_skip_client_cleanup(self):
        self.channel.close.side_effect = RuntimeError("SYNTHETIC-SECRET")
        with self.assertLogs("matrix_gui.util.exception_diagnostics", level="ERROR") as logs:
            self.dialog.reject()
        self.client.close.assert_called_once()
        self.assertIsNone(self.dialog._active_channel)
        self.assertNotIn("SYNTHETIC-SECRET", "\n".join(logs.output))

    def test_window_close_stops_timer_and_late_poll_is_harmless(self):
        self.dialog.show()
        self.dialog._poll_timer.start(10000)
        self.dialog.close()
        self.dialog._poll_ssh_channel()
        self.assertFalse(self.dialog._poll_timer.isActive())
        self.channel.close.assert_called_once()
        self.client.close.assert_called_once()

    def test_worker_keeps_gui_alive_and_close_cancels_connect_probe_and_upload(self):
        for phase in ("connect", "probe", "upload"):
            with self.subTest(phase=phase):
                entered, release = threading.Event(), threading.Event()
                client, channel = Mock(), Mock()
                client.get_transport.return_value.open_session.return_value = channel
                def hold(*args, **kwargs):
                    entered.set()
                    if not release.wait(3):
                        raise TimeoutError()
                def connect(*args):
                    if phase == "connect":
                        hold()
                    return client, "synthetic-pin"
                dialog = DeployDialog({}, deployment={"universe": "test"})
                worker = ControlSessionWorker({}, "synthetic", "start", {}, "synthetic", dialog)
                dialog._prepare_worker = worker
                worker.finished.connect(dialog._preparation_finished)
                beats = []
                timer = QtCore.QTimer()
                timer.timeout.connect(lambda: beats.append(True))
                timer.start(1)
                with patch("matrix_gui.modules.railgun.control_worker.connect_ssh_profile", side_effect=connect), patch("matrix_gui.modules.railgun.control_worker.verify_remote_matrixd_stdin", side_effect=hold if phase == "probe" else None), patch("matrix_gui.modules.railgun.control_worker.send_boot_envelope", side_effect=hold if phase == "upload" else None):
                    worker.start()
                    try:
                        limit = time.monotonic() + 2
                        while not entered.is_set() and time.monotonic() < limit:
                            self.app.processEvents()
                            time.sleep(.002)
                        self.assertTrue(entered.is_set())
                        for _ in range(5):
                            self.app.processEvents()
                            time.sleep(.002)
                        self.assertTrue(beats)
                        dialog.reject()
                        self.assertIs(dialog._prepare_worker, worker)
                        self.assertTrue(worker.cancelled.is_set())
                    finally:
                        release.set()
                        worker.wait(4000)  # Test teardown only; production never waits.
                        self.app.processEvents()
                        timer.stop()
                    self.assertIsNone(dialog._prepare_worker)
                    client.close.assert_called_once()
                    if phase == "upload":
                        channel.close.assert_called_once()
                        self.assertIn("unknown", dialog.output.toPlainText())
                    else:
                        channel.exec_command.assert_not_called()
                    dialog.deleteLater()

    def test_worker_success_handoff_then_late_cancel_closes_resources(self):
        client, channel = Mock(), Mock()
        client.get_transport.return_value.open_session.return_value = channel
        worker = ControlSessionWorker({}, "synthetic", "stop", None, None, self.dialog)
        with patch("matrix_gui.modules.railgun.control_worker.connect_ssh_profile", return_value=(client, "pin")), patch("matrix_gui.modules.railgun.control_worker.send_boot_envelope") as send:
            worker.run()
        send.assert_not_called()
        self.dialog._prepare_worker = worker
        worker.cancel()
        self.dialog._preparation_finished()
        client.close.assert_called_once()
        channel.close.assert_called_once()
        self.assertIsNone(self.dialog._active_channel)

    def test_stop_button_dispatches_worker_and_blocks_second_operation(self):
        target = {"host": "example.invalid", "username": "root", "auth_type": "password"}
        dialog = DeployDialog({"profile": target}, deployment={"universe": "test"})
        self.addCleanup(dialog.deleteLater)
        with patch.object(ControlSessionWorker, "start") as start:
            dialog._run_remote("stop")
            self.assertIsInstance(dialog._prepare_worker, ControlSessionWorker)
            self.assertEqual(dialog._prepare_worker.action, "stop")
            dialog._run_remote("stop")
            start.assert_called_once()
            self.assertIn("[BLOCKED]", dialog.output.toPlainText())
        dialog._prepare_worker = None

    def test_success_handoff_starts_polling_on_gui_thread(self):
        client, channel = Mock(), Mock()
        worker = ControlSessionWorker({}, "synthetic", "stop", None, None, self.dialog)
        worker.result = client, channel
        self.dialog._prepare_worker = worker
        self.dialog._preparation_finished()
        self.assertIs(self.dialog._active_channel, channel)
        self.assertTrue(self.dialog._poll_timer.isActive())
        self.assertEqual(self.dialog._poll_timer.thread(), self.app.thread())
        self.dialog._close_ssh_session()


if __name__ == "__main__":
    unittest.main()
