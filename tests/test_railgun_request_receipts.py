"""Durable request replay tests with disposable state and a fake executor."""
import importlib.machinery
import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from matrix_gui.modules.directive.deploy_dialog import DeployDialog
from matrix_gui.modules.railgun.request_identity import request_identity
from matrix_gui.modules.railgun.remote_shell import build_remote_matrixd_command


def load_server():
    loader = importlib.machinery.SourceFileLoader("railgun_receipt_test", str(ROOT / "matrixos/scripts/matrix-railgun-request"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class RequestReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.server = load_server()
        self.payload = json.dumps({"version": 1, "encrypted_bundle": {k: "eA==" for k in ("nonce", "tag", "ciphertext")}, "swarm_key": base64.b64encode(b"SYNTHETIC-SECRET-ONLY").decode()}).encode()
        self.execute = Mock(return_value=0)

    def run_request(self, request="a" * 32, universe="test", command="synthetic command", server=None):
        return (server or self.server).run_request(self.state, universe, request, command, self.payload, self.execute)

    def test_completed_receipt_survives_reload_without_replay(self):
        self.assertEqual(self.run_request(), 0)
        self.assertEqual(self.run_request(server=load_server()), 0)
        self.execute.assert_called_once()
        for path in self.state.glob("*.json"):
            self.assertNotIn("SYNTHETIC-SECRET", path.read_text())
            self.assertNotIn("synthetic command", path.read_text())

    def test_failed_command_receipt_is_not_reexecuted(self):
        self.execute.return_value = 9
        self.assertEqual(self.run_request(), 9)
        self.assertEqual(self.run_request(), 9)
        self.execute.assert_called_once()

    def test_changed_command_or_payload_with_same_id_is_blocked(self):
        self.run_request()
        with self.assertRaises(ValueError):
            self.run_request(command="different")
        self.payload += b" "
        with self.assertRaises(ValueError):
            self.run_request()
        self.execute.assert_called_once()

    def test_interruption_blocks_same_and_new_request_for_universe(self):
        self.execute.side_effect = EOFError("lost acknowledgement")
        with self.assertRaises(EOFError):
            self.run_request()
        for request in ("a" * 32, "b" * 32):
            with self.assertRaises(RuntimeError):
                self.run_request(request=request, server=load_server())
        self.execute.assert_called_once()

    def test_concurrent_different_request_is_blocked(self):
        def execute(command, payload):
            with self.assertRaises(RuntimeError):
                self.run_request(request="b" * 32)
            return 0
        self.execute.side_effect = execute
        self.run_request()
        self.execute.assert_called_once()

    def test_distinct_universes_and_intentional_new_request(self):
        self.run_request()
        self.run_request(request="b" * 32)
        self.run_request(universe="other")
        self.assertEqual(self.execute.call_count, 3)

    def test_receipt_write_failure_blocks_execution(self):
        with patch.object(self.server, "write_receipt", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.run_request()
        self.execute.assert_not_called()

    def test_incomplete_input_never_stops_existing_universe(self):
        self.payload = b'{"version":1'
        with self.assertRaises(ValueError):
            self.run_request()
        self.execute.assert_not_called()
        self.assertEqual(list(self.state.iterdir()), [])

    def test_explicit_request_wraps_entire_command(self):
        cmd = build_remote_matrixd_command(action="restart", universe="test", linux_user="matrix-test", request_id="a" * 32)
        self.assertIn("matrix-railgun-request", cmd)
        # kill/boot commands are inside the encoded operation, never ahead of receipt.
        self.assertNotIn(" kill --universe", cmd)
        self.assertNotIn(" boot --universe", cmd)
        self.assertIn("durable request wrapper missing", cmd)

    def test_identity_persists_new_intent_and_refuses_rejected_save(self):
        vault = Mock()
        vault.data = {}
        target = {"host": "server", "port": 22, "trusted_host_fingerprint": "pin"}
        original = request_identity(vault, target, {"universe": "test"})
        self.assertEqual(original, request_identity(vault, target, {"universe": "test"}))
        def save(key, value):
            vault.data[key] = value
            return True
        vault.patch.side_effect = save
        fresh = request_identity(vault, target, {"universe": "test"}, new_operation=True)
        self.assertNotEqual(original, fresh)
        self.assertEqual(fresh, request_identity(vault, target, {"universe": "test"}))

        vault.patch.side_effect = None
        vault.patch.return_value = False
        with self.assertRaises(RuntimeError):
            request_identity(vault, target, {"universe": "test"}, new_operation=True)
        self.assertEqual(fresh, request_identity(vault, target, {"universe": "test"}))

    def test_initial_retry_reuses_saved_identity_and_rejects_different_target(self):
        target = {"host": "example.invalid", "port": 22, "username": "root", "trusted_host_fingerprint": "synthetic"}
        opts = {"railgun_request_id": "a" * 32, "universe": "test", "linux_user": "matrix-test", "reboot": True}
        record = {"railgun_boot_options": opts, "universe": "test", "encrypted_bundle": {}, "swarm_key": "synthetic",
                  "railgun_target_identity": {"host": "example.invalid", "port": 22, "pin": "synthetic"}}
        dialog = DeployDialog({"profile": target}, deployment=record)
        self.addCleanup(dialog.deleteLater)
        with patch("matrix_gui.swarm_workspace.cls_lib.deployment.dialog.railgun.RailgunDialog.launch") as launch:
            dialog._retry_initial_request()
            self.assertEqual(launch.call_args.args[-1], opts)
            different = deepcopy(target)
            different["host"] = "different.invalid"
            dialog.ssh_selector.setItemData(0, different)
            dialog._retry_initial_request()
            launch.assert_called_once()

    def test_initial_retry_reports_invalid_data_and_launch_failure_without_leaks(self):
        target = {"host": "example.invalid", "port": 22, "username": "root", "trusted_host_fingerprint": "synthetic"}
        record = {"railgun_boot_options": {"railgun_request_id": "a" * 32},
                  "universe": "test", "encrypted_bundle": {}, "swarm_key": "SYNTHETIC-SECRET",
                  "railgun_target_identity": {"host": "example.invalid", "port": 22, "pin": "synthetic"}}
        for failure in ("port", "missing-key", "launch"):
            with self.subTest(failure=failure):
                dialog = DeployDialog({"profile": target}, deployment=deepcopy(record))
                self.addCleanup(dialog.deleteLater)
                if failure == "port":
                    dialog.ssh_selector.setItemData(0, {**target, "port": "SYNTHETIC-SECRET"})
                elif failure == "missing-key":
                    del dialog.deployment["swarm_key"]
                with patch("matrix_gui.swarm_workspace.cls_lib.deployment.dialog.railgun.RailgunDialog.launch", side_effect=RuntimeError("SYNTHETIC-SECRET")) as launch, self.assertLogs("matrix_gui.util.exception_diagnostics", level="ERROR") as logs:
                    dialog._retry_initial_request()
                if failure == "launch":
                    launch.assert_called_once()
                else:
                    launch.assert_not_called()
                self.assertIn("[ERROR]", dialog.output.toPlainText())
                self.assertNotIn("SYNTHETIC-SECRET", dialog.output.toPlainText())
                self.assertNotIn("SYNTHETIC-SECRET", "\n".join(logs.output))

    def test_initial_retry_blocks_while_another_operation_is_active(self):
        dialog = DeployDialog({}, deployment={"universe": "test"})
        self.addCleanup(dialog.deleteLater)
        dialog._active_channel = Mock()
        with patch("matrix_gui.swarm_workspace.cls_lib.deployment.dialog.railgun.RailgunDialog.launch") as launch:
            dialog._retry_initial_request()
            launch.assert_not_called()
        self.assertIn("[BLOCKED]", dialog.output.toPlainText())


if __name__ == "__main__":
    unittest.main()
