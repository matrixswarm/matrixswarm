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
from PyQt6.QtWidgets import QApplication, QCheckBox, QMessageBox, QPushButton, QToolButton
from matrix_gui.modules.directive.deploy_dialog import DeployDialog
from matrix_gui.modules.railgun.control_worker import ControlSessionWorker
from matrix_gui.modules.railgun.request_identity import (
    ControlIdentityError, request_identity, request_scope_key,
    session_control_identity,
)
from matrix_gui.modules.railgun.remote_shell import build_remote_matrixd_command
from matrix_gui.modules.vault.services.vault_connection_singleton import VaultConnectionSingleton


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

    def test_inactive_guard_is_inside_durable_lock_and_denial_is_not_replayed(self):
        checks = []
        def active(universe):
            checks.append(universe)
            self.assertTrue(list(self.state.glob("*.active")))
            return False
        self.assertEqual(73, self.server.run_request(self.state, "test", "a" * 32,
            "command", self.payload, self.execute, inactive_check=active))
        self.assertEqual(73, self.server.run_request(self.state, "test", "a" * 32,
            "command", self.payload, self.execute, inactive_check=lambda _: True))
        self.execute.assert_not_called()
        self.assertEqual(["test"], checks)

    def test_guard_cannot_be_removed_or_bypass_an_interrupted_universe_lock(self):
        self.execute.side_effect = EOFError("uncertain")
        with self.assertRaises(EOFError):
            self.server.run_request(self.state, "test", "a" * 32, "command",
                self.payload, self.execute, inactive_check=lambda _: True)
        with self.assertRaises(RuntimeError):
            self.server.run_request(self.state, "test", "b" * 32, "command",
                self.payload, self.execute, inactive_check=lambda _: True)
        self.execute.assert_called_once()

    def test_guarded_builder_rejects_restart_and_requires_new_server_protocol(self):
        command = build_remote_matrixd_command(action="start", universe="test",
            linux_user="matrix-test", request_id="a" * 32, require_inactive=True)
        self.assertIn("--require-inactive", command)
        self.assertIn("--inactive-protocol", command)
        for flags in (("--reboot",), ("--reboot-new",)):
            with self.assertRaises(ValueError):
                build_remote_matrixd_command(action="start", universe="test",
                    linux_user="matrix-test", boot_flags=flags, request_id="a" * 32, require_inactive=True)
        with self.assertRaises(ValueError):
            build_remote_matrixd_command(action="restart", universe="test",
                linux_user="matrix-test", request_id="a" * 32, require_inactive=True)

    def test_inactive_inspection_checks_any_agent_and_fails_closed_on_access_denied(self):
        import psutil
        agent = Mock()
        agent.cmdline.return_value = ["python", "run", "--job", "test:child-agent"]
        with patch.object(psutil, "process_iter", return_value=[agent]):
            self.assertFalse(self.server.universe_is_inactive("test"))
            self.assertTrue(self.server.universe_is_inactive("other"))
            agent.cmdline.side_effect = psutil.AccessDenied(42)
            with self.assertRaises(psutil.AccessDenied):
                self.server.universe_is_inactive("test")

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

    def test_session_control_identity_uses_live_deployment_and_vault_receipt(self):
        target = {"host": "example.invalid", "port": 22, "username": "root",
                  "trusted_host_fingerprint": "synthetic"}
        record = {"ssh_serial": "profile", "railgun_target_identity":
                  {"host": "example.invalid", "port": 22, "pin": "synthetic"},
                  "universe": "test", "label": "test", "linux_user": "matrix-test",
                  "encrypted_bundle": {"ciphertext": "synthetic"}, "agents": [],
                  "runtime_capabilities": {}}
        vault = Mock()
        vault._closed = False
        vault.data = {}
        vault.get_store.return_value.get_dep.return_value = record
        vault.read.return_value = {"registry": {"ssh": {"profile": target}}}
        vault.patch.side_effect = lambda key, value: vault.data.update({key: value}) or True
        flags = ["--protect-memory"]
        scope = request_scope_key(target, {"action": "restart", "universe": "test",
                                           "linux_user": "matrix-test", "flags": flags,
                                           "capabilities": {}, "bundle": record["encrypted_bundle"]})
        first = session_control_identity(vault, "dep-1", "restart", flags, scope,
                                         new_operation=True)
        self.assertEqual(first, session_control_identity(vault, "dep-1", "restart", flags,
                                                         scope, new_operation=False))
        second = session_control_identity(vault, "dep-1", "restart", flags, scope,
                                          new_operation=True)
        self.assertNotEqual(first, second)
        record["railgun_target_identity"]["host"] = "different.invalid"
        with self.assertRaises(ControlIdentityError):
            session_control_identity(vault, "dep-1", "restart", flags, scope,
                                     new_operation=True)
        self.assertEqual(vault.patch.call_count, 2)

    def test_session_pipe_waits_for_cockpit_control_receipt(self):
        class Pipe:
            def send(self, message):
                self.message = message
                self.response = {"type": "railgun.identity.response",
                                 "request_id": message["request_id"], "dep_id": "dep-1",
                                 "ok": True, "railgun_request_id": "a" * 32}

            def poll(self, _timeout):
                return hasattr(self, "response")

            def recv(self):
                response = self.response
                del self.response
                return response

        pipe = Pipe()
        connection = VaultConnectionSingleton("dep-1", pipe)
        self.assertEqual(connection.request_railgun_identity(
            "restart", ["--protect-memory"], "b" * 64, new_operation=True), "a" * 32)
        self.assertEqual(pipe.message["dep_id"], "dep-1")
        self.assertTrue(pipe.message["new_operation"])

    def test_session_control_is_bound_to_one_ssh_profile_and_new_restart(self):
        target = {"host": "example.invalid", "port": 22, "username": "root",
                  "auth_type": "password", "trusted_host_fingerprint": "synthetic"}
        other = {**target, "host": "other.invalid"}
        record = {"ssh_serial": "profile", "railgun_target_identity":
                  {"host": "example.invalid", "port": 22, "pin": "synthetic"},
                  "universe": "test", "label": "test", "linux_user": "matrix-test",
                  "encrypted_bundle": {}, "swarm_key": "synthetic", "agents": [],
                  "runtime_capabilities": {}}
        vault_connection = Mock()
        vault_connection.request_railgun_identity.return_value = "a" * 32
        dialog = DeployDialog({"profile": target, "other": other}, deployment=record,
                              vault_connection=vault_connection)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.ssh_selector.count(), 1)
        self.assertFalse(dialog.ssh_selector.isEnabled())
        self.assertTrue(dialog.universe_edit.isReadOnly())
        self.assertTrue(dialog.linux_user_edit.isReadOnly())
        self.assertFalse(any("intentional" in box.text() for box in dialog.findChildren(QCheckBox)))
        self.assertFalse(any("Retry initial" in button.text() for button in dialog.findChildren(QPushButton)))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(ControlSessionWorker, "start") as start:
            dialog._run_remote("restart")
        start.assert_called_once()
        vault_connection.request_railgun_identity.assert_called_once()
        self.assertTrue(vault_connection.request_railgun_identity.call_args.kwargs["new_operation"])
        dialog._prepare_worker = None
        dialog.ssh_selector.setItemData(0, other)
        dialog._run_remote("restart")
        self.assertIn("[BLOCKED]", dialog.output.toPlainText())
        vault_connection.request_railgun_identity.assert_called_once()

    def test_session_control_refuses_missing_or_changed_recorded_target(self):
        target = {"host": "example.invalid", "port": 22, "username": "root",
                  "trusted_host_fingerprint": "synthetic"}
        record = {"ssh_serial": "missing", "railgun_target_identity":
                  {"host": "example.invalid", "port": 22, "pin": "synthetic"},
                  "universe": "test", "label": "test"}
        dialog = DeployDialog({"profile": target}, deployment=record)
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.ssh_selector.isEnabled())
        self.assertIsNone(dialog._current_bound_target())
        self.assertIn("[BLOCKED]", dialog.output.toPlainText())
        legacy = dict(record)
        legacy.pop("ssh_serial")
        legacy_dialog = DeployDialog({"profile": target}, deployment=legacy)
        self.addCleanup(legacy_dialog.deleteLater)
        self.assertIsNone(legacy_dialog._current_bound_target())
        self.assertIn("Recorded SSH target unavailable", legacy_dialog.ssh_selector.itemText(0))

    def _control_dialog(self, action="restart"):
        target = {"host": "example.invalid", "port": 22, "username": "root",
                  "auth_type": "password", "trusted_host_fingerprint": "synthetic"}
        record = {"ssh_serial": "profile", "railgun_target_identity":
                  {"host": "example.invalid", "port": 22, "pin": "synthetic"},
                  "universe": "test", "label": "test", "linux_user": "matrix-test",
                  "encrypted_bundle": {}, "swarm_key": "synthetic", "agents": [],
                  "runtime_capabilities": {}}
        connection = Mock()
        connection.request_railgun_identity.return_value = "a" * 32
        dialog = DeployDialog({"profile": target}, deployment=record, vault_connection=connection)
        self.addCleanup(dialog.deleteLater)
        button = next(button for button in dialog.findChildren(QToolButton)
                      if button.text() == action.capitalize())
        return dialog, connection, button

    def test_start_and_restart_buttons_allocate_fresh_requests(self):
        for action in ("start", "restart"):
            with self.subTest(action=action):
                dialog, connection, button = self._control_dialog(action)
                connection.request_railgun_identity.side_effect = ["a" * 32, "b" * 32]
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                     patch.object(ControlSessionWorker, "start"):
                    button.click()
                    first = dialog._prepare_worker
                    dialog._prepare_worker = None
                    button.click()
                    second = dialog._prepare_worker
                self.assertIsNot(first, second)
                self.assertEqual(connection.request_railgun_identity.call_count, 2)
                self.assertTrue(all(call.kwargs["new_operation"] for call in
                                    connection.request_railgun_identity.call_args_list))
                self.assertEqual(dialog._control_requests[action]["request_id"], "b" * 32)
                dialog._prepare_worker = None

    def test_lost_reply_recovery_preserves_options_and_does_not_repeat_boot(self):
        dialog, connection, button = self._control_dialog()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(ControlSessionWorker, "start"):
            button.click()
            original = dialog._prepare_worker.command
            self.assertEqual(self.run_request(command=original), 0)
            dialog._prepare_worker = None
            dialog._active_channel = Mock()
            dialog._active_channel.recv_ready.side_effect = ConnectionError("lost reply")
            dialog._ssh_client = Mock()
            with self.assertLogs("matrix_gui.util.exception_diagnostics", level="ERROR"):
                dialog._poll_ssh_channel()
            # These are options for a future operation. Recovery must retain
            # the original bytes so the server can return the existing receipt.
            dialog.flag_debug.setChecked(True)
            dialog.flag_clean.setChecked(True)
            dialog._retry_control_actions["restart"].trigger()
            recovered = dialog._prepare_worker.command
            self.assertEqual(recovered, original)
            self.assertEqual(self.run_request(command=recovered, server=load_server()), 0)
        self.execute.assert_called_once()
        self.assertFalse(connection.request_railgun_identity.call_args.kwargs["new_operation"])
        self.assertEqual(connection.request_railgun_identity.call_args.args[1], ["--protect-memory"])
        dialog._prepare_worker = None

    def test_retry_refuses_changed_deployment_or_replaced_identity(self):
        for change in ("bundle", "receipt"):
            with self.subTest(change=change):
                dialog, connection, button = self._control_dialog()
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                     patch.object(ControlSessionWorker, "start") as start:
                    button.click()
                    dialog._prepare_worker = None
                    if change == "bundle":
                        dialog.deployment["encrypted_bundle"] = {"ciphertext": "changed"}
                    else:
                        connection.request_railgun_identity.return_value = "b" * 32
                    dialog._retry_control_actions["restart"].trigger()
                start.assert_called_once()
                self.assertIsNone(dialog._prepare_worker)
                self.assertIn("[BLOCKED]", dialog.output.toPlainText())
                self.assertEqual(connection.request_railgun_identity.call_count, 1 if change == "bundle" else 2)

    def test_control_retry_is_unavailable_before_a_request_and_blocked_during_one(self):
        dialog, connection, button = self._control_dialog()
        self.assertFalse(dialog._retry_control_actions["restart"].isEnabled())
        dialog._retry_control_request("restart")
        connection.request_railgun_identity.assert_not_called()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(ControlSessionWorker, "start") as start:
            button.click()
            self.assertTrue(dialog._retry_control_actions["restart"].isEnabled())
            dialog._retry_control_actions["restart"].trigger()
            start.assert_called_once()
        connection.request_railgun_identity.assert_called_once()
        dialog._prepare_worker = None

    def test_start_menu_recovers_original_deployment_launch(self):
        dialog, connection, button = self._control_dialog("start")
        dialog.deployment["railgun_boot_options"] = {"railgun_request_id": "c" * 32}
        # Rebuild against the saved record, as the production dialog does.
        dialog = DeployDialog(dialog.ssh_map, deployment=dialog.deployment, vault_connection=connection)
        self.addCleanup(dialog.deleteLater)
        button = next(button for button in dialog.findChildren(QToolButton) if button.text() == "Start")
        retry = next(action for action in button.menu().actions() if action.text() == "Retry saved deployment launch")
        self.assertTrue(retry.isEnabled())
        with patch("matrix_gui.swarm_workspace.cls_lib.deployment.dialog.railgun.RailgunDialog.launch") as launch:
            retry.trigger()
        self.assertEqual(launch.call_args.args[-1], {"railgun_request_id": "c" * 32})
        connection.request_railgun_identity.assert_not_called()

    def test_recovery_survives_reopening_control_in_the_same_session(self):
        dialog, connection, button = self._control_dialog()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(ControlSessionWorker, "start"):
            button.click()
            original = dialog._prepare_worker.command
            dialog._prepare_worker = None
            dialog.reject()
            reopened = DeployDialog(dialog.ssh_map, deployment=dialog.deployment, vault_connection=connection)
            self.addCleanup(reopened.deleteLater)
            reopened.flag_debug.setChecked(True)
            self.assertTrue(reopened._retry_control_actions["restart"].isEnabled())
            reopened._retry_control_actions["restart"].trigger()
            self.assertEqual(reopened._prepare_worker.command, original)
            self.assertFalse(connection.request_railgun_identity.call_args.kwargs["new_operation"])
            reopened._prepare_worker = None

    def test_session_restart_never_connects_without_vault_receipt(self):
        target = {"host": "example.invalid", "port": 22, "username": "root",
                  "auth_type": "password", "trusted_host_fingerprint": "synthetic"}
        record = {"ssh_serial": "profile", "railgun_target_identity":
                  {"host": "example.invalid", "port": 22, "pin": "synthetic"},
                  "universe": "test", "label": "test", "linux_user": "matrix-test",
                  "encrypted_bundle": {}, "swarm_key": "synthetic", "agents": [],
                  "runtime_capabilities": {}}
        vault_connection = Mock()
        vault_connection.request_railgun_identity.side_effect = RuntimeError(
            "The vault could not save a new control request; nothing was sent.")
        dialog = DeployDialog({"profile": target}, deployment=record,
                              vault_connection=vault_connection)
        self.addCleanup(dialog.deleteLater)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(ControlSessionWorker, "start") as start:
            dialog._run_remote("restart")
        start.assert_not_called()
        self.assertIsNone(dialog._prepare_worker)
        self.assertIn("[BLOCKED]", dialog.output.toPlainText())
        self.assertNotIn("[SSH] Connecting", dialog.output.toPlainText())

    def test_initial_retry_reuses_saved_identity_and_rejects_different_target(self):
        target = {"host": "example.invalid", "port": 22, "username": "root", "trusted_host_fingerprint": "synthetic"}
        opts = {"railgun_request_id": "a" * 32, "universe": "test", "linux_user": "matrix-test", "reboot": True}
        record = {"railgun_boot_options": opts, "universe": "test", "encrypted_bundle": {}, "swarm_key": "synthetic",
                  "ssh_serial": "profile",
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
                  "ssh_serial": "profile",
                  "railgun_target_identity": {"host": "example.invalid", "port": 22, "pin": "synthetic"}}
        for failure in ("port", "missing-key", "launch"):
            with self.subTest(failure=failure):
                dialog = DeployDialog({"profile": target}, deployment=deepcopy(record))
                self.addCleanup(dialog.deleteLater)
                if failure == "port":
                    dialog.ssh_selector.setItemData(0, {**target, "port": "SYNTHETIC-SECRET"})
                elif failure == "missing-key":
                    del dialog.deployment["swarm_key"]
                with patch("matrix_gui.swarm_workspace.cls_lib.deployment.dialog.railgun.RailgunDialog.launch", side_effect=RuntimeError("SYNTHETIC-SECRET")) as launch:
                    if failure == "port":
                        dialog._retry_initial_request()
                        logs = []
                    else:
                        with self.assertLogs("matrix_gui.util.exception_diagnostics", level="ERROR") as captured:
                            dialog._retry_initial_request()
                        logs = captured.output
                if failure == "launch":
                    launch.assert_called_once()
                else:
                    launch.assert_not_called()
                self.assertTrue("[ERROR]" in dialog.output.toPlainText()
                                or "[BLOCKED]" in dialog.output.toPlainText())
                self.assertNotIn("SYNTHETIC-SECRET", dialog.output.toPlainText())
                self.assertNotIn("SYNTHETIC-SECRET", "\n".join(logs))

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
