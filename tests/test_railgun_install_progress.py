"""Offline worker and real Qt responsiveness tests; no servers are contacted."""

import importlib
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QDialog
except ImportError:
    QApplication = None


PROFILE = {"host": "example.test", "username": "root", "port": 22,
           "auth_type": "private_key", "private_key": "test-only",
           "trusted_host_fingerprint": "SHA256:test-only"}


class Channel:
    def __init__(self, code=0, delay=0, out=b"", err=b""):
        self.code, self.delay = code, delay
        self.out, self.err = out, err
        self.closed = False
        self.command = None
        self.started = 0

    def settimeout(self, timeout):
        self.timeout = timeout

    def get_pty(self):
        pass

    def exec_command(self, command):
        self.command = command
        self.started = time.monotonic()

    def recv_ready(self):
        return bool(self.out)

    def recv_stderr_ready(self):
        return bool(self.err)

    def recv(self, size):
        out, self.out = self.out[:size], self.out[size:]
        return out

    def recv_stderr(self, size):
        err, self.err = self.err[:size], self.err[size:]
        return err

    def exit_status_ready(self):
        return time.monotonic() - self.started >= self.delay

    def recv_exit_status(self):
        return self.code

    def close(self):
        self.closed = True


class SFTP:
    def __init__(self, delay=0, fail_put=False, fail_script=False):
        self.delay, self.fail_put, self.fail_script = delay, fail_put, fail_script
        self.puts, self.dirs, self.script_paths = [], [], []
        self.closed = False
        self.thread_ids = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def get_channel(self):
        return self

    def settimeout(self, value):
        self.timeout = value

    def mkdir(self, path):
        self.dirs.append(path)

    def put(self, local, remote, callback):
        self.thread_ids.append(threading.get_ident())
        if self.fail_put:
            raise TimeoutError("SFTP transfer timed out")
        size = os.path.getsize(local)
        for current in (0, size // 2, size):
            if self.delay:
                time.sleep(self.delay)
            callback(current, size)
        self.puts.append((local, remote))

    def file(self, path, mode):
        if self.fail_script:
            raise OSError("Cannot write installer script")
        self.script_paths.append(path)
        return io.StringIO()

    def chmod(self, path, mode):
        pass


class Client:
    def __init__(self, *, code=0, delay=0, fail_put=False, fail_script=False):
        self.staging = Channel()
        self.installer = Channel(code, delay, b"final stdout", b"final stderr")
        self.channels = []
        self.sftps = []
        self.options = (delay, fail_put, fail_script)
        self.closed = False
        self.active = True

    def get_transport(self):
        return self

    def set_keepalive(self, interval):
        self.keepalive = interval

    def open_session(self, timeout):
        channel = self.staging if not self.channels else self.installer
        self.channels.append(channel)
        return channel

    def is_active(self):
        return self.active

    def open_sftp(self):
        sftp = SFTP(*self.options)
        self.sftps.append(sftp)
        return sftp

    def close(self):
        self.closed = True


@unittest.skipIf(QApplication is None, "Phoenix GUI dependencies not installed")
class RailgunInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.module = importlib.import_module("matrix_gui.modules.railgun.railgun_install_dialog")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def add_file(self, relative, content="test"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def worker(self, mode="Local Full Install"):
        worker = self.module.RailgunInstallWorker(PROFILE, mode, str(self.root), "skip")
        worker.messages, worker.stages, worker.progress = [], [], []
        worker.output.connect(worker.messages.append)
        worker.stage.connect(worker.stages.append)
        worker.upload_progress.connect(worker.progress.append)
        return worker

    def run_worker(self, client=None, mode="Local Full Install"):
        worker = self.worker(mode)
        client = client or Client()
        with mock.patch.object(self.module, "connect_ssh_profile", return_value=(client, "SHA256:test")):
            worker.run()
        return worker, client

    def test_manifest_preserves_selection_and_flat_directory_rules(self):
        expected = ("agents/a.py", "agents/sub/b.json", "core/lib.py",
                    "scripts/matrixd", "boot_directives/boot.json", "maxmind/config.txt",
                    "requirements.txt", ".env", "root.PY")
        ignored = ("agents/a.pyc", "scripts/nested/no.py", "boot_directives/nested/no.json",
                   "maxmind/database.mmdb", ".venv/no.py", "universes/secret.json",
                   "backups/data.json", "root.exe")
        for path in expected + ignored:
            self.add_file(path)
        (self.root / "core/empty").mkdir()
        dirs, files = self.worker()._build_upload_plan()
        self.assertEqual(set(expected), {entry[1] for entry in files})
        self.assertIn("core/empty", dirs)
        self.assertEqual(4 * len(expected), sum(entry[2] for entry in files))
        for directory in dirs:
            if "/" in directory:
                self.assertLess(dirs.index(directory.rsplit("/", 1)[0]), dirs.index(directory))

    def test_empty_or_missing_source_fails_before_connect(self):
        worker = self.worker()
        with mock.patch.object(self.module, "connect_ssh_profile") as connect:
            worker.run()
        connect.assert_not_called()
        self.assertFalse(worker.success)
        self.assertIn("No eligible", worker.error)
        worker.local_src = str(self.root / "missing")
        with self.assertRaisesRegex(ValueError, "directory"):
            worker._build_upload_plan()

    def test_success_transfers_counts_bytes_and_drains_final_output(self):
        self.add_file("agents/a.py", "12345")
        self.add_file("core/empty.py", "")
        worker, client = self.run_worker()
        self.assertTrue(worker.success)
        self.assertEqual((2, 2, 5, 5, ""), worker.progress[-1])
        self.assertIn("final stdout", worker.messages)
        self.assertIn("[ERROR] final stderr", worker.messages)
        self.assertEqual(2, len(client.sftps[0].puts))
        self.assertTrue(all(s.closed for s in client.sftps))
        self.assertTrue(all(c.closed for c in client.channels))
        self.assertTrue(client.closed)
        self.assertEqual({}, worker.ssh_cfg)
        self.assertIn("PYTHON_MODE=skip bash /tmp/matrix_staging_", client.installer.command)

    def test_github_skips_local_scan_and_source_upload(self):
        worker = self.worker("Install from GitHub")
        client = Client()
        with mock.patch.object(worker, "_build_upload_plan", side_effect=AssertionError("Must not scan")), \
                mock.patch.object(self.module, "connect_ssh_profile", return_value=(client, "SHA256:test")):
            worker.run()
        self.assertTrue(worker.success)
        self.assertEqual(1, len(client.sftps))
        self.assertEqual([], client.sftps[0].puts)
        self.assertEqual([], worker.progress)

    def test_connect_failure_is_reported_and_profile_snapshot_cleared(self):
        worker = self.worker("Install from GitHub")
        with mock.patch.object(self.module, "connect_ssh_profile", side_effect=ValueError("Host-key mismatch")):
            worker.run()
        self.assertFalse(worker.success)
        self.assertIn("Host-key mismatch", worker.error)
        self.assertEqual({}, worker.ssh_cfg)
        self.assertEqual("test-only", PROFILE["private_key"])

    def test_transfer_failure_closes_resources_and_does_not_launch(self):
        self.add_file("agents/a.py")
        worker, client = self.run_worker(Client(fail_put=True))
        self.assertFalse(worker.success)
        self.assertIn("timed out", worker.error)
        self.assertIsNone(client.installer.command)
        self.assertTrue(client.sftps[0].closed)
        self.assertTrue(client.closed)

    def test_script_upload_failure_does_not_launch(self):
        worker, client = self.run_worker(Client(fail_script=True), "Install from GitHub")
        self.assertFalse(worker.success)
        self.assertIsNone(client.installer.command)
        self.assertTrue(client.sftps[0].closed)
        self.assertTrue(client.closed)

    def test_nonzero_or_missing_exit_code_is_not_success(self):
        for code in (1, -1):
            with self.subTest(code=code):
                worker, client = self.run_worker(Client(code=code), "Install from GitHub")
                self.assertFalse(worker.success)
                self.assertIn(f"exit code {code}", worker.error)
                self.assertTrue(any("no rollback" in msg for msg in worker.messages))
                self.assertTrue(client.closed)

    def test_staging_failure_never_uploads_or_runs_installer(self):
        client = Client()
        client.staging.code = 1
        worker, client = self.run_worker(client, "Install from GitHub")
        self.assertFalse(worker.success)
        self.assertEqual([], client.sftps)
        self.assertTrue(client.closed)

    def test_staging_deadline_and_disconnect_are_reported(self):
        worker = self.worker()
        channel = Channel(delay=100)
        channel.exec_command("test")
        client = Client()
        with self.assertRaises(TimeoutError):
            worker._drain_channel(channel, client, timeout=0)
        client.active = False
        with self.assertRaises(ConnectionError):
            worker._drain_channel(channel, client)

    def test_source_size_change_aborts_before_upload(self):
        path = self.add_file("agents/a.py", "before")
        worker = self.worker()
        plan = worker._build_upload_plan()
        path.write_text("changed size", encoding="utf-8")
        sftp = SFTP()
        with self.assertRaisesRegex(RuntimeError, "Source changed"):
            worker._upload_plan(sftp, plan, "/tmp/test")
        self.assertEqual([], sftp.puts)

    def test_zero_byte_files_still_finish_progress(self):
        self.add_file("core/empty.py", "")
        worker, _ = self.run_worker()
        self.assertTrue(worker.success)
        self.assertEqual((1, 1, 0, 0, ""), worker.progress[-1])

    def make_dialog(self, dialog_class=None):
        with mock.patch.object(self.module, "load_registry_ssh_profiles", return_value={"test": PROFILE}):
            dialog = (dialog_class or self.module.RailgunInstallDialog)()
        dialog.mode_selector.setCurrentText("Local Full Install")
        dialog.local_path.setText(str(self.root))
        dialog.show()
        self.app.processEvents()
        return dialog

    def pump_until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(predicate(), "Qt worker did not complete in time")

    def test_real_qt_stays_responsive_during_connect_and_upload(self):
        self.add_file("agents/a.py", "123456789")
        client = Client(delay=0.12)
        callback_threads, connection_threads, ticks = [], [], []
        base = self.module.RailgunInstallDialog

        class RecordingDialog(base):
            def _show_upload_progress(self, progress):
                callback_threads.append(threading.get_ident())
                super()._show_upload_progress(progress)

        dialog = self.make_dialog(RecordingDialog)
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(dialog._install_running))
        timer.start()

        def connect(profile):
            connection_threads.append(threading.get_ident())
            time.sleep(0.2)
            return client, "SHA256:test"

        try:
            with mock.patch.object(self.module, "load_registry_ssh_profiles", return_value={"test": PROFILE}), \
                    mock.patch.object(self.module, "connect_ssh_profile", side_effect=connect) as connector:
                started = time.monotonic()
                dialog.run_installer()
                self.assertLess(time.monotonic() - started, 0.15)
                worker = dialog.install_thread
                self.assertFalse(dialog.btn_install.isEnabled())
                self.assertFalse(dialog.local_path.isEnabled())
                self.assertFalse(dialog.ssh_selector.isEnabled())
                dialog.run_installer()  # double click does not start another worker
                dialog.close()
                dialog.reject()  # Escape
                dialog.done(QDialog.DialogCode.Rejected)
                self.assertTrue(dialog.isVisible())
                self.assertIs(worker, dialog.install_thread)
                self.pump_until(lambda: not dialog._install_running)
                self.assertEqual(1, connector.call_count)
            self.assertGreater(sum(ticks), 15)
            self.assertEqual([threading.get_ident()], list(set(callback_threads)))
            self.assertTrue(all(t != threading.get_ident() for t in connection_threads))
            self.assertTrue(all(t != threading.get_ident() for t in client.sftps[0].thread_ids))
            self.assertIn("Installation complete", dialog.status_label.text())
            self.assertEqual(1000, dialog.progress_bar.value())
            self.assertTrue(dialog.btn_install.isEnabled())
            self.assertTrue(dialog.ssh_selector.isEnabled())
            self.assertFalse(dialog.elapsed_timer.isActive())
            self.assertIn("final stderr", dialog.output_box.toPlainText())
            self.assertIn("1/1 files", dialog.upload_label.text())
        finally:
            timer.stop()
            if dialog.install_thread:
                dialog.install_thread.wait(5000)
                self.app.processEvents()
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

    def test_qt_error_restores_controls_and_allows_retry(self):
        dialog = self.make_dialog()
        dialog.mode_selector.setCurrentText("Install from GitHub")
        try:
            with mock.patch.object(self.module, "load_registry_ssh_profiles", return_value={"test": PROFILE}), \
                    mock.patch.object(self.module, "connect_ssh_profile", side_effect=ValueError("Authentication failed")):
                dialog.run_installer()
                self.pump_until(lambda: not dialog._install_running)
            self.assertIn("Installation failed", dialog.status_label.text())
            self.assertIn("Authentication failed", dialog.output_box.toPlainText())
            self.assertTrue(dialog.btn_install.isEnabled())
            self.assertIsNone(dialog.install_thread)
            with mock.patch.object(self.module, "load_registry_ssh_profiles", return_value={"test": PROFILE}), \
                    mock.patch.object(self.module, "connect_ssh_profile", return_value=(Client(), "SHA256:test")):
                dialog.run_installer()
                self.pump_until(lambda: not dialog._install_running)
            self.assertIn("Installation complete", dialog.status_label.text())
        finally:
            if dialog.install_thread:
                dialog.install_thread.wait(5000)
                self.app.processEvents()
            dialog.close()
            dialog.deleteLater()

    def test_large_byte_counts_and_upload_completion_are_distinct(self):
        dialog = self.make_dialog()
        try:
            size = 8 * 1024 ** 3
            dialog._show_upload_progress((0, 1, size, size, "large.py"))
            self.assertLess(dialog.progress_bar.value(), 1000)
            self.assertIn("8.0 GiB", dialog.upload_label.text())
            dialog._show_upload_progress((1, 1, size, size, ""))
            self.assertEqual(1000, dialog.progress_bar.value())
            dialog._set_stage("Running remote installer")
            self.assertEqual((0, 0), (dialog.progress_bar.minimum(), dialog.progress_bar.maximum()))
            dialog._append_output("<b>plain server output</b>")
            self.assertIn("<b>plain server output</b>", dialog.output_box.toPlainText())
            self.assertIn("from Registry.\n<b>", dialog.output_box.toPlainText())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_thread_start_failure_restores_controls(self):
        dialog = self.make_dialog()
        try:
            with mock.patch.object(self.module, "load_registry_ssh_profiles", return_value={"test": PROFILE}), \
                    mock.patch.object(self.module.RailgunInstallWorker, "start", side_effect=RuntimeError("Cannot start thread")):
                dialog.run_installer()
            self.assertFalse(dialog._install_running)
            self.assertIsNone(dialog.install_thread)
            self.assertTrue(dialog.btn_install.isEnabled())
            self.assertIn("Cannot start thread", dialog.output_box.toPlainText())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_removed_profile_never_silently_switches_target(self):
        dialog = self.make_dialog()
        try:
            with mock.patch.object(self.module, "load_registry_ssh_profiles", return_value={"other": PROFILE}), \
                    mock.patch.object(self.module.RailgunInstallWorker, "start") as start:
                dialog.run_installer()
            start.assert_not_called()
            self.assertFalse(dialog._install_running)
            self.assertIn("no longer available", dialog.output_box.toPlainText())
        finally:
            dialog.close()
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
