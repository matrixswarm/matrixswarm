"""Offline adversarial checks for the operator-controlled diagnostic tool belt."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "phoenix"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_bridge import FakeEventBus, FakeCockpit, FakeVault, FakeConnection, FakeProcess
from phoenix_terminal.bridge.phoenix_backend import PhoenixBackend
from phoenix_terminal.bridge.permissions import CursorBuffer
from phoenix_terminal.cli import build_parser, run_bridge


class AssignmentTests(unittest.TestCase):
    def setUp(self):
        self.events = FakeEventBus()
        self.cockpit = FakeCockpit()
        self.vault = FakeVault()
        self.vault.deployments["demo"]["agents"][0].update({
            "name": "matrix_ssh", "config": {
                "poll_interval": 1, "batch_limit": 32,
                "security": {"private_key": "SECRET-PRIVATE"}, "password": "SECRET-PASSWORD",
            },
        })
        self.seal()
        self.vault.deployments["excluded"] = {
            "label": "Other", "agents": [{"universal_id": "private-agent", "name": "matrix_ssh"}],
        }
        self.vault.snapshot = lambda name: deepcopy(self.vault.deployments) if name == "deployments" else {}
        self.saves = []
        self.allow_save = True

        def transform(name, callback):
            candidate = callback(deepcopy(self.vault.deployments))
            if not self.allow_save:
                return False
            self.vault.deployments = candidate
            self.saves.append(deepcopy(candidate))
            return True
        self.vault.transform_section = transform
        self.core = type("Core", (), {"get": lambda _: self.vault})()
        self.backend = PhoenixBackend(self.cockpit, self.events, self.core)
        self.events.emit("vault.unlocked")
        self.backend.enable_assignment(["demo"])

    def seal(self, root=None):
        import base64
        from matrix_gui.modules.vault.crypto.deploy_tools import encrypt_data
        root = deepcopy(root if root is not None else self.vault.deployments["demo"]["agents"])
        self.vault.deployments["demo"]["swarm_key"] = base64.b64encode(b"T" * 32).decode()
        self.vault.deployments["demo"]["encrypted_bundle"] = encrypt_data(json.dumps(root).encode(), b"T" * 32)

    def unseal(self):
        from matrix_gui.modules.vault.crypto.deploy_tools import decrypt_swarm_encrypted_directive
        dep = self.vault.deployments["demo"]
        return decrypt_swarm_encrypted_directive(dep["encrypted_bundle"], dep["swarm_key"])

    def call(self, method, **params):
        return self.backend.handle(method, params)

    def request_edit(self, request_id="edit-1", **changes):
        return self.call("agent.config.set", deployment_id="demo", agent_id="watcher-1",
                         changes=changes or {"poll_interval": 5}, request_id=request_id)

    def approve(self, request_id, approved=True):
        self.backend.resolve_action(request_id, approved, self.backend._assignment_id)

    def test_assignment_denies_other_deployments_agents_and_runtime_ids(self):
        self.cockpit.session_processes.append({"session_id": "outside-runtime", "deployment_id": "excluded",
                                              "proc": FakeProcess(), "conn": FakeConnection()})
        self.assertEqual(["demo"], [d["id"] for d in self.call("deployment.list")["deployments"]])
        self.assertEqual(1, len(self.call("session.list")["sessions"]))
        for method, params in [
            ("agent.list", {"deployment_id": "excluded"}),
            ("agent.describe", {"deployment_id": "demo", "agent_id": "private-agent"}),
            ("agent.tree", {"session_id": "outside-runtime"}),
            ("agent.restart", {"session_id": "outside-runtime", "agent_id": "private-agent", "request_id": "x"}),
        ]:
            with self.subTest(method=method), self.assertRaises(ValueError):
                self.call(method, **params)
        self.assertEqual([], self.cockpit.connection.messages)

    def test_new_inventory_is_not_implicitly_granted(self):
        self.vault.deployments["demo"]["agents"].append({"universal_id": "new-agent", "name": "matrix_ssh"})
        self.assertEqual(1, len(self.call("agent.list", deployment_id="demo")["agents"]))
        with self.assertRaises(ValueError):
            self.call("agent.describe", deployment_id="demo", agent_id="new-agent")

    def test_describe_exports_only_numeric_config_and_action_hints(self):
        config = self.vault.deployments["demo"]["agents"][0]["config"]
        config["batch_limit"] = "SECRET-IN-NUMERIC-FIELD"
        self.seal()
        result = self.call("agent.describe", deployment_id="demo", agent_id="watcher-1")
        text = json.dumps(result)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("private_key", text)
        self.assertIsNone(result["configuration"]["values"]["batch_limit"])
        self.assertEqual(1, result["configuration"]["values"]["poll_interval"])
        tools = {t["name"]: t for t in self.call("tools.describe")["tools"]}
        self.assertTrue(tools["agent.config.set"]["operator_approval"])
        self.assertFalse(tools["agent.logs.read"]["operator_approval"])

    def test_unknown_fields_and_approval_bypass_rejected(self):
        for method, params in [
            ("action.approve", {"request_id": "x"}),
            ("vault.dump", {}),
            ("agent.restart", {"session_id": "runtime-123", "agent_id": "watcher-1",
                               "request_id": "x", "approved": True}),
            ("agent.tree", {"session_id": "runtime-123", "refresh": "false"}),
            ("agent.logs.read", {"subscription_id": "x", "after": True}),
        ]:
            with self.subTest(method=method), self.assertRaises(ValueError):
                self.call(method, **params)
        for changes in ({"password": "new"}, {"config.poll_interval": 1},
                        {"poll_interval": True}, {"poll_interval": 0}, {"batch_limit": 129}, {}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.call("agent.config.set", deployment_id="demo", agent_id="watcher-1",
                          request_id="x", changes=changes)
        self.assertEqual({}, self.backend._actions)

    def test_save_requires_exact_approval_preserves_secrets_and_avoids_live_change(self):
        self.vault.deployments["demo"]["railgun_request_id"] = "original"
        self.vault.deployments["demo"]["railgun_boot_options"] = {"railgun_request_id": "original", "protect_memory": True}
        self.assertEqual("pending", self.request_edit()["state"])
        self.assertEqual([], self.saves)
        prompt = self.backend.pending_approval()
        self.assertIn('"poll_interval": 5', prompt["text"])
        self.assertNotIn("SECRET", prompt["text"])
        self.approve("edit-1")
        result = self.call("action.status", request_id="edit-1")
        self.assertEqual("saved", result["state"])
        self.assertFalse(result["result"]["running_agent_changed"])
        config = self.vault.deployments["demo"]["agents"][0]["config"]
        self.assertEqual(5, config["poll_interval"])
        self.assertEqual("SECRET-PRIVATE", config["security"]["private_key"])
        self.assertEqual("SECRET-PASSWORD", config["password"])
        self.assertNotIn("railgun_request_id", self.vault.deployments["demo"])
        self.assertEqual({"protect_memory": True}, self.vault.deployments["demo"]["railgun_boot_options"])
        sealed = self.unseal()[0]["config"]
        self.assertEqual(5, sealed["poll_interval"])
        self.assertEqual("SECRET-PRIVATE", sealed["security"]["private_key"])
        self.assertEqual("SECRET-PASSWORD", sealed["password"])
        self.assertEqual([], self.cockpit.connection.messages)
        self.assertEqual("saved", self.request_edit()["state"])
        self.approve("edit-1")
        self.assertEqual(1, len(self.saves))

    def test_tree_inventory_and_sealed_config_work_without_public_config_copy(self):
        import hashlib
        agent = deepcopy(self.vault.deployments["demo"]["agents"][0])
        directive = {"name": "matrix", "universal_id": "matrix", "config": {}, "children": [agent]}
        self.seal(directive)
        private = deepcopy(directive)
        private["children"][0]["config"] = {}
        self.vault.deployments["demo"]["agents"] = private
        self.backend.enable_assignment(["demo"])
        self.assertEqual(2, len(self.call("agent.list", deployment_id="demo")["agents"]))
        result = self.call("agent.describe", deployment_id="demo", agent_id="watcher-1")
        self.assertEqual(1, result["configuration"]["values"]["poll_interval"])
        self.request_edit(poll_interval=7)
        self.approve("edit-1")
        self.assertEqual(7, self.unseal()["children"][0]["config"]["poll_interval"])
        dep = self.vault.deployments["demo"]
        self.assertEqual({}, dep["agents"]["children"][0]["config"])
        expected = hashlib.sha256(json.dumps(dep["encrypted_bundle"], sort_keys=True,
                                             separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(expected, dep["encrypted_hash"])

    def test_corrupted_or_mismatched_sealed_directive_cannot_be_edited(self):
        original = deepcopy(self.vault.deployments["demo"])
        self.vault.deployments["demo"]["encrypted_bundle"]["tag"] = "AAAAAAAAAAAAAAAAAAAAAA=="
        with self.assertRaises(ValueError):
            self.request_edit()
        self.vault.deployments["demo"] = deepcopy(original)
        self.seal([{"name": "different_agent", "universal_id": "watcher-1", "config": {}}])
        with self.assertRaises(ValueError):
            self.request_edit()
        self.assertEqual({}, self.backend._actions)
        self.assertEqual([], self.saves)

    def test_request_payload_is_detached_and_id_cannot_change_meaning(self):
        changes = {"poll_interval": 5}
        self.call("agent.config.set", deployment_id="demo", agent_id="watcher-1",
                  request_id="edit-1", changes=changes)
        changes["poll_interval"] = 99
        with self.assertRaises(ValueError):
            self.request_edit(poll_interval=99)
        self.approve("edit-1")
        self.assertEqual(5, self.vault.deployments["demo"]["agents"][0]["config"]["poll_interval"])

    def test_denial_expiry_and_changed_deployment_never_save(self):
        self.request_edit("denied")
        self.approve("denied", False)
        self.approve("denied", True)
        self.assertEqual("denied", self.call("action.status", request_id="denied")["state"])
        self.request_edit("expired")
        self.backend._actions["expired"]["deadline"] = 0
        self.approve("expired")
        self.assertEqual("expired", self.call("action.status", request_id="expired")["state"])
        self.request_edit("changed")
        self.vault.deployments["demo"]["agents"][0]["config"]["password"] = "rotated"
        self.approve("changed")
        self.assertEqual("stale", self.call("action.status", request_id="changed")["state"])
        self.assertEqual([], self.saves)

    def test_vault_changed_inside_persistence_transaction_is_rejected(self):
        self.request_edit()
        original = self.vault.transform_section
        def concurrent_change(name, callback):
            self.vault.deployments["demo"]["agents"][0]["config"]["batch_limit"] = 17
            return original(name, callback)
        self.vault.transform_section = concurrent_change
        self.approve("edit-1")
        self.assertEqual([], self.saves)
        self.assertEqual(1, self.vault.deployments["demo"]["agents"][0]["config"]["poll_interval"])
        self.assertEqual("uncertain", self.call("action.status", request_id="edit-1")["state"])

    def test_failed_save_is_not_reported_successful(self):
        self.request_edit()
        self.allow_save = False
        self.approve("edit-1")
        self.assertEqual("uncertain", self.call("action.status", request_id="edit-1")["state"])
        self.assertEqual(1, self.vault.deployments["demo"]["agents"][0]["config"]["poll_interval"])

    def test_revocation_clears_access_and_old_approval_cannot_authorize_new_assignment(self):
        self.request_edit()
        previous = self.backend._assignment_id
        self.backend.disable_bridge()
        for method, params in [("session.list", {}), ("agent.tree", {"session_id": "runtime-123"}),
                               ("action.status", {"request_id": "edit-1"})]:
            with self.assertRaises(PermissionError):
                self.call(method, **params)
        self.backend.enable_assignment(["demo"])
        self.request_edit()
        self.backend.resolve_action("edit-1", True, previous)
        self.assertEqual("pending", self.call("action.status", request_id="edit-1")["state"])
        self.events.emit("vault.closed")
        self.assertIsNone(self.backend.pending_approval())
        self.assertEqual([], self.saves)

    def test_restart_once_and_stale_session_rejected(self):
        params = {"session_id": "runtime-123", "agent_id": "watcher-1", "request_id": "restart-1"}
        self.call("agent.restart", **params)
        self.assertEqual([], self.cockpit.connection.messages)
        self.approve("restart-1")
        self.assertEqual("dispatched", self.call("agent.restart", **params)["state"])
        self.approve("restart-1")
        self.assertEqual([{"type": "bridge.restart", **params}], self.cockpit.connection.messages)
        self.call("agent.restart", **dict(params, request_id="restart-2"))
        self.cockpit.session_processes[0]["conn"] = FakeConnection()
        self.approve("restart-2")
        self.assertEqual("stale", self.call("action.status", request_id="restart-2")["state"])

    def test_request_launch_does_not_connect_until_approval(self):
        self.cockpit.session_processes = []
        calls = []
        self.cockpit.launch_session = lambda *args: calls.append(args)
        self.call("deployment.launch", deployment_id="demo", request_id="connect")
        self.assertEqual([], calls)
        self.approve("connect", False)
        self.assertEqual([], calls)

    def test_inflight_limit_bounds_unattended_prompts(self):
        for index in range(8):
            self.request_edit(str(index))
        with self.assertRaises(ValueError):
            self.request_edit("overflow")
        self.assertEqual(8, len(self.backend._actions))

    def test_log_cursor_survives_eviction_and_reports_gap(self):
        stream = CursorBuffer(3)
        stream.append(["a", "b", "c"])
        self.assertEqual(2, stream.read(0, 2)["next_cursor"])
        stream.append(["d", "e"])
        page = stream.read(2)
        self.assertEqual(["c", "d", "e"], page["items"])
        self.assertFalse(page["gap"])
        self.assertEqual(5, page["next_cursor"])
        self.assertTrue(stream.read(0)["gap"])
        with self.assertRaises(ValueError):
            stream.read(6)

    def test_alerts_and_tree_are_scoped_and_redacted(self):
        self.backend.handle_session_message({"type": "swarm_feed", "event": {
            "session_id": "runtime-123", "payload": {"password": "HIDDEN", "message": "slow"}}})
        self.backend.handle_session_message({"type": "swarm_feed", "event": {
            "session_id": "unknown", "payload": "outside"}})
        page = self.call("session.alerts", session_id="runtime-123")
        self.assertEqual(1, len(page["items"]))
        self.assertNotIn("HIDDEN", json.dumps(page))
        self.backend.handle_session_message({"type": "bridge.agent_tree", "session_id": "runtime-123",
                                             "agents": [{"universal_id": "watcher-1"}, {"universal_id": "outside"}]})
        self.assertEqual(1, len(self.call("agent.tree", session_id="runtime-123", refresh=False)["agents"]))

    def test_log_callback_cannot_cross_sessions(self):
        result = self.call("agent.logs.start", session_id="runtime-123", agent_id="watcher-1", follow=False)
        subscription_id = result["subscription_id"]
        self.backend.handle_session_message({"type": "bridge.log", "session_id": "other",
                                             "subscription_id": subscription_id, "lines": ["outside"]})
        self.assertEqual([], self.call("agent.logs.read", subscription_id=subscription_id)["lines"])
        self.backend.handle_session_message({"type": "bridge.log", "session_id": "runtime-123",
                                             "subscription_id": subscription_id, "lines": ["password=hidden"], "follow": False})
        result = self.call("agent.logs.read", subscription_id=subscription_id)
        self.assertEqual("complete", result["state"])
        self.assertNotIn("hidden", json.dumps(result))

    def test_retired_gui_action_cannot_dispatch_from_cli(self):
        parser = build_parser()
        args = parser.parse_args(["bridge", "config-set", "demo", "watcher-1",
                                  "--changes", '{"poll_interval": 5}', "--request-id", "one"])
        with patch("phoenix_terminal.cli.call_bridge", return_value={"state": "pending"}) as bridge, patch("builtins.print"):
            with self.assertRaisesRegex(ValueError, "retired"):
                run_bridge(args)
        bridge.assert_not_called()
        self.assertFalse(hasattr(args, "approved"))


class AssignmentQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_selection_defaults_empty_and_prompt_no_is_default(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QMessageBox
        from phoenix_terminal.bridge.approval_ui import AssignmentDialog, ApprovalPresenter
        test = AssignmentTests()
        test.setUp()
        dialog = AssignmentDialog(test.backend.available_assignments())
        self.assertEqual([], dialog.selected_ids())
        self.assertFalse(dialog.ok_button.isEnabled())
        dialog.deployments.item(0).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(dialog.ok_button.isEnabled())
        presenter = ApprovalPresenter(test.backend)
        presenter.timer.stop()
        test.request_edit()
        presenter.poll()
        self.assertEqual(QMessageBox.StandardButton.No, presenter.prompt.standardButton(presenter.prompt.defaultButton()))
        presenter.prompt.button(QMessageBox.StandardButton.No).click()
        self.app.processEvents()
        self.assertEqual("denied", test.call("action.status", request_id="edit-1")["state"])
        self.assertEqual([], test.saves)
        presenter.close_prompt()
        dialog.close()

    def test_prompt_approval_saves_once_and_revocation_closes_it(self):
        from PyQt6.QtWidgets import QMessageBox
        from phoenix_terminal.bridge.approval_ui import ApprovalPresenter
        test = AssignmentTests()
        test.setUp()
        presenter = ApprovalPresenter(test.backend)
        presenter.timer.stop()
        test.request_edit()
        presenter.poll()
        presenter.prompt.button(QMessageBox.StandardButton.Yes).click()
        self.app.processEvents()
        self.assertEqual(1, len(test.saves))
        self.assertEqual("saved", test.call("action.status", request_id="edit-1")["state"])
        test.request_edit("second", poll_interval=6)
        presenter.poll()
        test.backend.disable_bridge()
        presenter.poll()
        self.assertIsNone(presenter.prompt)
        self.assertEqual(1, len(test.saves))

    def test_gui_restart_uses_shared_operation_contract(self):
        from matrix_gui.core.class_lib.services.agent_actions import restart_agent
        packets = []
        bus = type("Bus", (), {"emit": lambda _, name, **kw: packets.append((name, kw))})()
        restart_agent(bus, "session", "agent", False, "request")
        event, envelope = packets[0]
        packet = envelope["packet"].get_packet()
        self.assertEqual("outbound.message", event)
        self.assertEqual("outgoing.command", envelope["channel"])
        self.assertEqual("cmd_restart_subtree", packet["handler"])
        self.assertFalse(packet["content"]["restart_full_subtree"])
        self.assertEqual("request", packet["content"]["token"])

    def test_http_request_qt_approval_and_status_round_trip(self):
        import threading
        import time
        from tempfile import TemporaryDirectory
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QMessageBox
        from phoenix_terminal.bridge.approval_ui import ApprovalPresenter
        from phoenix_terminal.bridge.qt_dispatcher import QtBridgeDispatcher
        from phoenix_terminal.bridge.server import BridgeServer
        from phoenix_terminal.bridge_client import call_bridge
        test = AssignmentTests()
        test.setUp()
        dispatcher = QtBridgeDispatcher(test.backend)
        presenter = ApprovalPresenter(test.backend)
        presenter.timer.stop()
        with TemporaryDirectory() as directory:
            server = BridgeServer(dispatcher.call, Path(directory))
            server.start()
            def rpc(method, params):
                answers, errors = [], []
                def request():
                    try:
                        answers.append(call_bridge(Path(directory), method, params, timeout=5))
                    except Exception as exc:
                        errors.append(exc)
                thread = threading.Thread(target=request, daemon=True)
                thread.start()
                deadline = time.monotonic() + 6
                while thread.is_alive() and time.monotonic() < deadline:
                    self.app.processEvents()
                    QTest.qWait(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual([], errors)
                return answers[0]
            try:
                result = rpc("agent.config.set", {"deployment_id": "demo", "agent_id": "watcher-1",
                                                  "changes": {"batch_limit": 64}, "request_id": "http-edit"})
                self.assertEqual("pending", result["state"])
                self.assertEqual([], test.saves)
                presenter.poll()
                presenter.prompt.button(QMessageBox.StandardButton.Yes).click()
                self.app.processEvents()
                result = rpc("action.status", {"request_id": "http-edit"})
                self.assertEqual("saved", result["state"])
                self.assertEqual(64, test.vault.deployments["demo"]["agents"][0]["config"]["batch_limit"])
            finally:
                presenter.close_prompt()
                server.stop()

    def test_expired_qt_dispatch_never_reaches_backend(self):
        from phoenix_terminal.bridge.qt_dispatcher import QtBridgeDispatcher, _Ticket
        calls = []
        backend = type("Backend", (), {"handle": lambda _, *args: calls.append(args)})()
        dispatcher = QtBridgeDispatcher(backend)
        ticket = _Ticket("agent.restart", {}, deadline=0)
        dispatcher._execute(ticket)
        self.assertEqual([], calls)
        self.assertTrue(ticket.done.is_set())
        self.assertIsInstance(ticket.error, TimeoutError)
