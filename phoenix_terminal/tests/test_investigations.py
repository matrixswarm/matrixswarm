"""Investigation continuity without client secrets or fabricated durable evidence."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import test_assignments
from test_bridge import FakeConnection, FakeProcess
from phoenix_terminal.bridge.investigations import SECTION, MAX_INVESTIGATIONS
from phoenix_terminal.bridge.phoenix_backend import PhoenixBackend
from phoenix_terminal.bridge.permissions import CursorBuffer
from phoenix_terminal.cli import build_parser, run_investigation


class InvestigationTests(unittest.TestCase):
    def setUp(self):
        fixture = test_assignments.AssignmentTests()
        fixture.setUp()
        self.fixture = fixture
        self.backend = fixture.backend
        self.vault = fixture.vault
        self.cockpit = fixture.cockpit
        self.events = fixture.events
        self.records = {}
        self.saved = []
        self.allow_save = True
        self.vault.snapshot = lambda name: deepcopy(self.vault.deployments if name == "deployments" else self.records if name == SECTION else {})
        def transform(name, callback):
            self.assertEqual(SECTION, name)
            candidate = callback(deepcopy(self.records))
            if not self.allow_save:
                return False
            self.records = candidate
            self.saved.append(deepcopy(candidate))
            return True
        self.vault.transform_section = transform

    def call(self, method, **params):
        return self.backend.handle(method, params)

    def opened(self, investigation_id="case-one"):
        return self.call("investigation.open", investigation_id=investigation_id, deployment_id="demo", agent_id="watcher-1")

    def attach(self, **kwargs):
        return self.call("investigation.attach", investigation_id="case-one", session_id="runtime-123", **kwargs)

    def read(self, stream="logs", **kwargs):
        return self.call("investigation.read", investigation_id="case-one", stream=stream, **kwargs)

    def ack(self, receipt):
        return self.call("investigation.ack", investigation_id="case-one", receipt=receipt)

    def lines(self, lines):
        binding = self.backend._investigation_bindings["case-one"]
        self.backend.handle_session_message({
            "type": "bridge.log", "session_id": "runtime-123",
            "subscription_id": binding["subscription_id"], "lines": lines,
        })

    def test_open_resume_offline_no_remote_operation_or_credential_projection(self):
        self.cockpit.session_processes.clear()
        before = deepcopy(self.vault.deployments)
        result = self.opened()
        self.assertEqual("selected", result["state"])
        self.assertEqual([], result["sessions"])
        self.assertEqual("not_attached", result["streams"]["logs"]["state"])
        self.assertEqual("encrypted_phoenix_vault", result["storage"])
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("deployment_revision", result)
        self.assertEqual(before, self.vault.deployments)
        self.assertEqual({}, self.backend._actions)
        self.assertEqual([], self.cockpit.connection.messages)
        self.assertEqual("case-one", self.call("investigation.list")["investigations"][0]["investigation_id"])
        self.assertEqual(result, self.opened())
        self.assertEqual(1, len(self.saved))

    def test_recreated_backend_restores_only_selection(self):
        self.opened()
        self.attach()
        self.lines(["one", "two"])
        page = self.read(limit=1)
        self.ack(page["receipt"])
        old_id = self.backend._assignment_id
        self.backend.close()
        self.backend = PhoenixBackend(self.cockpit, self.events, self.fixture.core)
        self.events.emit("vault.unlocked")
        self.backend.enable_assignment(["demo"])
        self.assertNotEqual(old_id, self.backend._assignment_id)
        result = self.call("investigation.resume", investigation_id="case-one")
        self.assertEqual(1, result["streams"]["logs"]["acknowledged_cursor"])
        self.assertEqual("history_unavailable", result["streams"]["logs"]["state"])
        self.assertEqual({}, self.backend._actions)
        self.assertEqual({}, self.backend._subscriptions)
        with self.assertRaisesRegex(ValueError, "reset=true"):
            self.attach()
        self.attach(reset=True)
        self.assertEqual(0, self.read()["next_cursor"])
        with self.assertRaises(ValueError):
            self.ack(page["receipt"])

    def test_read_requires_explicit_ack_and_duplicate_ack_never_rewinds(self):
        self.opened()
        self.attach()
        self.lines(["one", "two", "three"])
        first = self.read(limit=1)
        self.assertEqual(["one"], first["items"])
        self.assertEqual(["one"], self.read(limit=1)["items"])
        self.assertEqual(0, self.records["case-one"]["streams"]["logs"]["cursor"])
        self.ack(first["receipt"])
        second = self.read(limit=2)
        self.assertEqual(["two", "three"], second["items"])
        self.ack(second["receipt"])
        self.assertEqual(3, self.ack(first["receipt"])["acknowledged_cursor"])
        self.assertEqual([], self.read()["items"])
        self.assertNotIn("one", json.dumps(self.records["case-one"]["streams"]))

    def test_alerts_have_independent_review_position_and_redaction(self):
        self.opened()
        self.attach()
        self.lines(["line"])
        self.backend.handle_session_message({"type": "swarm_feed", "event": {
            "session_id": "runtime-123", "payload": {"message": "slow", "password": "HIDDEN"}}})
        page = self.read("alerts")
        self.assertEqual(1, len(page["items"]))
        self.assertNotIn("HIDDEN", json.dumps(page))
        self.ack(page["receipt"])
        self.assertEqual(["line"], self.read()["items"])
        self.assertEqual([], self.read("alerts")["items"])

    def test_rollover_exposes_gap_and_absolute_cursor(self):
        self.opened()
        self.attach()
        sub = self.backend._subscriptions[self.backend._investigation_bindings["case-one"]["subscription_id"]]
        sub["buffer"] = CursorBuffer(2)
        self.lines(["lost", "two", "three"])
        result = self.call("investigation.resume", investigation_id="case-one")
        self.assertTrue(result["streams"]["logs"]["gap"])
        page = self.read()
        self.assertTrue(page["gap"])
        self.assertEqual(1, page["oldest_cursor"])
        self.assertEqual(3, page["next_cursor"])
        self.assertEqual(["two", "three"], page["items"])
        self.ack(page["receipt"])
        self.assertFalse(self.read()["gap"])

    def test_repeated_attach_is_idempotent(self):
        self.opened()
        self.attach()
        messages = deepcopy(self.cockpit.connection.messages)
        self.attach()
        self.attach(reset=True)
        self.assertEqual(messages, self.cockpit.connection.messages)
        self.assertEqual(1, len(self.backend._subscriptions))

    def test_replaced_connection_or_process_invalidates_receipts_and_alerts(self):
        self.opened()
        self.attach()
        self.lines(["old"])
        old_page = self.read()
        old_alerts = self.backend._investigation_bindings["case-one"]["alerts"]
        old_alerts.append(["old-alert"])
        self.cockpit.session_processes[0]["conn"] = FakeConnection()
        with self.assertRaises(ValueError):
            self.ack(old_page["receipt"])
        self.attach(reset=True)
        self.assertEqual([], self.read("alerts")["items"])
        self.assertIsNot(old_alerts, self.backend._investigation_bindings["case-one"]["alerts"])
        page = self.read()
        self.cockpit.session_processes[0]["proc"] = FakeProcess()
        with self.assertRaises(ValueError):
            self.ack(page["receipt"])

    def test_stopped_session_and_wrong_deployment_cannot_attach(self):
        self.opened()
        self.cockpit.session_processes[0]["proc"] = None
        with self.assertRaisesRegex(ValueError, "not running"):
            self.attach()
        self.assertEqual({}, self.records["case-one"]["streams"])
        self.vault.deployments["second"] = deepcopy(self.vault.deployments["demo"])
        self.backend.enable_assignment(["demo", "second"])
        self.cockpit.session_processes.append({"session_id": "other", "deployment_id": "second",
                                              "proc": FakeProcess(), "conn": FakeConnection()})
        with self.assertRaisesRegex(ValueError, "does not belong"):
            self.call("investigation.attach", investigation_id="case-one", session_id="other")

    def test_current_assignment_always_rechecked(self):
        self.opened()
        self.attach()
        page = self.read()
        self.backend.enable_assignment(["excluded"])
        self.assertEqual([], self.call("investigation.list")["investigations"])
        for method, params in [
            ("investigation.resume", {}),
            ("investigation.read", {"stream": "logs"}),
            ("investigation.ack", {"receipt": page["receipt"]}),
        ]:
            with self.subTest(method=method), self.assertRaises(ValueError):
                self.call(method, investigation_id="case-one", **params)
        self.backend.disable_bridge()
        with self.assertRaises(PermissionError):
            self.call("investigation.list")

    def test_removed_agent_and_changed_deployment_cannot_reuse_old_identity(self):
        self.opened()
        self.vault.deployments["demo"]["label"] = "Changed deployment"
        result = self.call("investigation.resume", investigation_id="case-one")
        self.assertEqual("stale", result["state"])
        with self.assertRaisesRegex(ValueError, "changed"):
            self.attach()
        with self.assertRaises(ValueError):
            self.opened()
        self.assertEqual("selected", self.opened("case-two")["state"])
        self.vault.deployments["demo"]["agents"].clear()
        self.assertEqual([], self.call("investigation.list")["investigations"])
        with self.assertRaises(ValueError):
            self.call("investigation.resume", investigation_id="case-two")

    def test_no_other_vault_records_and_no_arbitrary_imported_field_projection(self):
        self.opened()
        for bad in [
            {**self.records["case-one"], "password": "SECRET"},
            {**self.records["case-one"], "streams": {"logs": {"cursor": "SECRET"}}},
            {**self.records["case-one"], "created_at": True},
        ]:
            self.records["bad"] = bad
            with self.assertRaises(ValueError):
                self.call("investigation.resume", investigation_id="bad")
            self.assertEqual(1, len(self.call("investigation.list")["investigations"]))
        self.records = {}  # Another vault has its own section even if deployment IDs match.
        with self.assertRaises(ValueError):
            self.call("investigation.resume", investigation_id="case-one")

    def test_id_collision_and_cap_fail_closed(self):
        self.opened()
        self.backend.enable_assignment(["demo", "excluded"])
        with self.assertRaisesRegex(ValueError, "different selection"):
            self.call("investigation.open", investigation_id="case-one",
                      deployment_id="excluded", agent_id="private-agent")
        self.records = {str(i): deepcopy(self.records["case-one"]) for i in range(MAX_INVESTIGATIONS)}
        with self.assertRaisesRegex(ValueError, "capacity"):
            self.opened()
        self.assertEqual(MAX_INVESTIGATIONS, len(self.records))

    def test_failed_save_or_racing_update_does_not_advance_checkpoint(self):
        self.opened()
        self.attach()
        self.lines(["one"])
        page = self.read()
        self.allow_save = False
        with self.assertRaisesRegex(RuntimeError, "not saved"):
            self.ack(page["receipt"])
        self.assertEqual(0, self.records["case-one"]["streams"]["logs"]["cursor"])
        self.allow_save = True
        transform = self.vault.transform_section
        def raced(name, callback):
            self.records["case-one"]["created_at"] += 1
            return transform(name, callback)
        self.vault.transform_section = raced
        with self.assertRaisesRegex(ValueError, "changed"):
            self.ack(page["receipt"])
        self.assertEqual(0, self.records["case-one"]["streams"]["logs"]["cursor"])

    def test_failed_attach_persistence_does_not_send_and_failed_send_not_ready(self):
        self.opened()
        self.allow_save = False
        with self.assertRaises(RuntimeError):
            self.attach()
        self.assertEqual([], self.cockpit.connection.messages)
        self.allow_save = True
        with patch.object(self.cockpit.connection, "send", side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                self.attach()
        self.assertEqual({}, self.backend._subscriptions)
        result = self.call("investigation.resume", investigation_id="case-one")
        self.assertEqual("history_unavailable", result["streams"]["logs"]["state"])

    def test_receipts_are_scoped_expiring_not_caller_supplied_cursors(self):
        self.opened()
        self.attach()
        self.opened("case-two")
        self.call("investigation.attach", investigation_id="case-two", session_id="runtime-123")
        page = self.read()
        with self.assertRaises(ValueError):
            self.call("investigation.ack", investigation_id="case-two", receipt=page["receipt"])
        with self.assertRaises(ValueError):
            self.call("investigation.ack", investigation_id="case-one", receipt=page["receipt"], cursor=999)
        self.backend._review_receipts[page["receipt"]]["expires"] = 0
        with self.assertRaises(ValueError):
            self.ack(page["receipt"])
        with self.assertRaises(ValueError):
            self.read("credentials")
        with self.assertRaises(ValueError):
            self.call("investigation.attach", investigation_id="case-one", session_id="runtime-123", reset="true")

    def test_real_vault_encrypted_roundtrip_and_restart_resume(self):
        from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
        from matrix_gui.modules.vault.crypto.vault_handler import save_vault_singlefile, load_vault_singlefile
        from matrix_gui.core.event_bus import EventBus
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "fixture.json")
            vault = VaultCoreSingleton({"deployments": deepcopy(self.vault.deployments)}, "fixture-only", path)
            def save(event, **kwargs):
                if event == "vault.update":
                    save_vault_singlefile(kwargs["data"], kwargs["password"], kwargs["vault_path"])
                    kwargs["receipt"]["saved"] = True
            self.fixture.core.get = lambda: vault
            with patch.object(EventBus, "emit", side_effect=save):
                self.opened()
                self.attach()
                self.lines(["ephemeral-evidence"])
                self.ack(self.read()["receipt"])
            raw = Path(path).read_text()
            self.assertNotIn("case-one", raw)
            self.assertNotIn("SECRET", raw)
            restored = load_vault_singlefile("fixture-only", path)
            self.assertEqual(1, restored[SECTION]["case-one"]["streams"]["logs"]["cursor"])
            self.assertNotIn("ephemeral-evidence", json.dumps(restored))
            self.backend.close()
            vault2 = VaultCoreSingleton(restored, "fixture-only", path)
            self.fixture.core.get = lambda: vault2
            self.backend = PhoenixBackend(self.cockpit, self.events, self.fixture.core)
            self.events.emit("vault.unlocked")
            self.backend.enable_assignment(["demo"])
            result = self.call("investigation.resume", investigation_id="case-one")
            self.assertEqual(1, result["streams"]["logs"]["acknowledged_cursor"])
            self.assertEqual("history_unavailable", result["streams"]["logs"]["state"])

    def test_retired_gui_investigations_do_not_dispatch_from_cli(self):
        for args, method, params in [
            (["list"], "list", {}),
            (["open", "one", "demo", "watcher-1"], "open",
             {"investigation_id": "one", "deployment_id": "demo", "agent_id": "watcher-1"}),
            (["resume", "one"], "resume", {"investigation_id": "one"}),
            (["attach", "one", "runtime-123", "--reset"], "attach",
             {"investigation_id": "one", "session_id": "runtime-123", "reset": True}),
            (["read", "one", "logs", "--limit", "5"], "read",
             {"investigation_id": "one", "stream": "logs", "limit": 5}),
            (["ack", "one", "receipt"], "ack", {"investigation_id": "one", "receipt": "receipt"}),
        ]:
            parsed = build_parser().parse_args(["investigation"] + args)
            with patch("phoenix_terminal.cli.call_bridge", return_value={}) as call, patch("builtins.print"):
                with self.assertRaisesRegex(ValueError, "retired"):
                    run_investigation(parsed)
                call.assert_not_called()
        tools = {t["name"]: t for t in self.call("tools.describe")["tools"]}
        self.assertIn("investigation.resume", tools)
        self.assertFalse(tools["investigation.ack"]["operator_approval"])
