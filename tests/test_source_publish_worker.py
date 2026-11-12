"""Source publication uses the recorded pinned SSH connection and verified reply."""
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from matrix_gui.modules.railgun import source_publish_worker as module
from PyQt6.QtWidgets import QApplication, QDialog
from matrix_gui.core.panel import replace_agent_panel as panel_module


class FakeChannel:
    def __init__(self, reply, status=0):
        self.reply = json.dumps(reply).encode()
        self.status = status
        self.sent = b""
        self.command = None
        self.closed = False
    def settimeout(self, value): pass
    def exec_command(self, command): self.command = command
    def sendall(self, data): self.sent += data
    def shutdown_write(self): pass
    def recv_ready(self): return bool(self.reply) and self.status == 0
    def recv(self, count): data, self.reply = self.reply[:count], self.reply[count:]; return data
    def recv_stderr_ready(self): return bool(self.reply) and self.status != 0
    def recv_stderr(self, count): data, self.reply = self.reply[:count], self.reply[count:]; return data
    def exit_status_ready(self): return True
    def recv_exit_status(self): return self.status
    def close(self): self.closed = True


class FakeTransport:
    def __init__(self, channel): self.channel = channel
    def is_active(self): return True
    def open_session(self, timeout): return self.channel


class FakeClient:
    def __init__(self, channel): self.transport = FakeTransport(channel); self.closed = False
    def get_transport(self): return self.transport
    def close(self): self.closed = True


class SourcePublishWorkerTests(unittest.TestCase):
    def run_worker(self, reply, status=0, *, name="example", profile=None):
        source = b"VALUE = 2\n"
        profile = profile or {"username": "admin", "trusted_host_fingerprint": "SHA256:pinned"}
        channel = FakeChannel(reply, status)
        client = FakeClient(channel)
        worker = module.SourcePublishWorker(profile, name, source)
        outcomes = []
        worker.result.connect(lambda result, error: outcomes.append((result, error)))
        with patch.object(module, "connect_ssh_profile", return_value=(client, "verified")) as connect:
            worker.run()
        return outcomes, connect, channel, client

    def test_sends_bytes_to_fixed_root_publisher_and_checks_hash(self):
        digest = hashlib.sha256(b"VALUE = 2\n").hexdigest()
        outcomes, connect, channel, client = self.run_worker({"status": "success", "agent": "example", "sha256": digest})
        self.assertIsNone(outcomes[0][1])
        self.assertEqual(connect.call_args.args[0]["trusted_host_fingerprint"], "SHA256:pinned")
        self.assertTrue(channel.command.startswith("sudo -n -- /bin/sh -c "))
        self.assertIn("matrix_source_publish.py", channel.command)
        self.assertIn("check_owned", channel.command)
        self.assertEqual(channel.sent, b"VALUE = 2\n")
        self.assertTrue(channel.closed and client.closed)

    def test_mismatched_confirmation_is_never_success(self):
        outcomes, _, _, _ = self.run_worker({"status": "success", "agent": "example", "sha256": "0" * 64})
        self.assertIsNone(outcomes[0][0])
        self.assertIn("did not match", outcomes[0][1])

    def test_rejects_unsafe_agent_name_before_connecting(self):
        outcomes, connect, _, _ = self.run_worker({}, name="../escape")
        connect.assert_not_called()
        self.assertIn("Invalid agent name", outcomes[0][1])

    def test_lost_ssh_reply_reports_unknown_outcome(self):
        channel = FakeChannel({})
        channel.recv = lambda count: (_ for _ in ()).throw(EOFError("connection lost"))
        client = FakeClient(channel)
        worker = module.SourcePublishWorker({"username": "root"}, "example", b"VALUE = 2\n")
        outcomes = []
        worker.result.connect(lambda result, error: outcomes.append((result, error)))
        with patch.object(module, "connect_ssh_profile", return_value=(client, "verified")):
            worker.run()
        self.assertIsNone(outcomes[0][0])
        self.assertIn("outcome may be unknown", outcomes[0][1])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux shell preflight required")
    def test_preflight_refuses_writable_or_linked_publisher_and_core(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            scripts = base / "scripts"
            core = base / "core"
            venv_bin = base / ".venv/bin"
            for path in (scripts, core, venv_bin):
                path.mkdir(parents=True)
                path.chmod(0o755)
            venv_bin.parent.chmod(0o755)
            publisher = scripts / "matrix_source_publish.py"
            publisher.write_text("print('REACHED')\n")
            publisher.chmod(0o644)
            safe_core = core / "safe.py"
            safe_core.write_text("pass\n")
            safe_core.chmod(0o644)
            (venv_bin / "python3").symlink_to("/usr/bin/python3")
            preflight = module._publisher_preflight(_base=str(base), _admin_uid=os.geteuid())
            def run():
                return subprocess.run(["/bin/sh", "-c", preflight, "--"], capture_output=True, text=True)
            result = run()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("REACHED", result.stdout)
            safe_core.chmod(0o666)
            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("REACHED", result.stdout)
            safe_core.chmod(0o644)
            safe_core.unlink()
            safe_core.symlink_to("/etc/passwd")
            self.assertNotEqual(run().returncode, 0)
            safe_core.unlink()
            publisher.unlink()
            publisher.symlink_to("/etc/passwd")
            self.assertNotEqual(run().returncode, 0)
            publisher.unlink()
            publisher.write_text("print('REACHED')\n")
            publisher.chmod(0o644)
            (venv_bin / "python3").unlink()
            untrusted_python = base / "untrusted-python"
            untrusted_python.write_text("#!/bin/sh\nexit 0\n")
            untrusted_python.chmod(0o755)
            (venv_bin / "python3").symlink_to(untrusted_python)
            self.assertNotEqual(run().returncode, 0)


class FakeSignal:
    def __init__(self): self.listeners = []
    def connect(self, callback): self.listeners.append(callback)
    def emit(self, *args):
        for callback in self.listeners: callback(*args)


class FakeWorker:
    def __init__(self, profile, name, source):
        self.profile, self.name, self.source = profile, name, source
        self.result, self.finished = FakeSignal(), FakeSignal()
    def start(self): pass
    def isRunning(self): return True
    def deleteLater(self): pass


class FakeDialog:
    def __init__(self, path): self.path = path
    def get_selection(self): return self.path, "example"
    def deleteLater(self): pass


class ReplaceSourcePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_uses_recorded_profile_and_reports_only_verified_result(self):
        import tempfile
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "example.py"
            source_path.write_text("VALUE = 2\n")
            conn = Mock()
            vault = Mock()
            vault.fetch_fresh.return_value = {"ssh": {"recorded": {"host": "expected", "trusted_host_fingerprint": "SHA256:pinned"}, "other": {"host": "different"}}}
            panel = panel_module.ReplaceAgentPanel("session", None, conn, {"ssh_serial": "recorded",
                "railgun_target_identity": {"host": "expected", "port": 22, "pin": "SHA256:pinned"}}, vault_connection=vault)
            panel._dlg = FakeDialog(str(source_path))
            with patch.object(panel_module, "SourcePublishWorker", FakeWorker):
                panel._on_finished(QDialog.DialogCode.Accepted)
            vault.fetch_fresh.assert_called_once_with(target="registry")
            worker = panel._worker
            self.assertEqual(worker.profile["host"], "expected")
            conn.send.assert_not_called()
            worker.result.emit({"agent": "example", "sha256": "a" * 64}, None)
            self.assertEqual(conn.send.call_count, 2)
            self.assertIn("embedded", conn.send.call_args.args[0]["message"])
            worker.finished.emit()
            self.assertIsNone(panel._worker)

    def test_changed_recorded_target_is_refused_before_connecting(self):
        import tempfile
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "example.py"
            source_path.write_text("VALUE = 2\n")
            vault = Mock()
            vault.fetch_fresh.return_value = {"ssh": {"recorded": {"host": "other", "trusted_host_fingerprint": "SHA256:new"}}}
            panel = panel_module.ReplaceAgentPanel("session", None, None, {"ssh_serial": "recorded",
                "railgun_target_identity": {"host": "original", "port": 22, "pin": "SHA256:old"}}, vault_connection=vault)
            panel._dlg = FakeDialog(str(source_path))
            with patch.object(panel_module, "SourcePublishWorker", FakeWorker), \
                 patch.object(panel_module.QMessageBox, "warning") as warning, \
                 patch.object(panel_module, "emit_gui_exception_log"):
                panel._on_finished(QDialog.DialogCode.Accepted)
            warning.assert_called_once()
            self.assertIsNone(panel._worker)

    def test_host_port_pin_mismatch_and_missing_profile_are_all_refused(self):
        import tempfile
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "example.py"
            source_path.write_text("VALUE = 2\n")
            recorded = {"host": "expected", "port": 22, "pin": "SHA256:pinned"}
            for changed in ({"host": "other", "port": 22, "trusted_host_fingerprint": "SHA256:pinned"},
                            {"host": "expected", "port": 2222, "trusted_host_fingerprint": "SHA256:pinned"},
                            {"host": "expected", "port": 22, "trusted_host_fingerprint": "SHA256:other"},
                            None):
                with self.subTest(changed=changed):
                    vault = Mock()
                    vault.fetch_fresh.return_value = {"ssh": {"recorded": changed} if changed is not None else {}}
                    panel = panel_module.ReplaceAgentPanel("session", None, None,
                        {"ssh_serial": "recorded", "railgun_target_identity": recorded}, vault_connection=vault)
                    panel._dlg = FakeDialog(str(source_path))
                    with patch.object(panel_module, "SourcePublishWorker", FakeWorker), \
                         patch.object(panel_module.QMessageBox, "warning") as warning, \
                         patch.object(panel_module, "emit_gui_exception_log"):
                        panel._on_finished(QDialog.DialogCode.Accepted)
                    vault.fetch_fresh.assert_called_once_with(target="registry")
                    warning.assert_called_once()
                    self.assertIsNone(panel._worker)

    def test_session_passes_its_ipc_vault_connection_to_panel(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from matrix_gui.core import session_window as session_module
        class FakePanel:
            def __init__(self, **kwargs): self.arguments = kwargs; self.launched = False
            def launch(self): self.launched = True
        vault = Mock()
        session = SimpleNamespace(_replace_panel=None, session_id="session", bus=None, conn=None,
                                  deployment={}, vault_singleton=vault)
        with patch.object(session_module, "ReplaceAgentPanel", FakePanel):
            session_module.SessionWindow._launch_replace_agent_source(session)
        self.assertIs(session._replace_panel.arguments["vault_connection"], vault)
        self.assertTrue(session._replace_panel.launched)


if __name__ == "__main__":
    unittest.main()
