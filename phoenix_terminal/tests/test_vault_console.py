"""Synthetic encrypted vaults and loopback only; no real operator credentials."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings

from phoenix_terminal import vault_console as console
from phoenix_terminal.bridge_client import call_bridge
from phoenix_terminal.cli import build_parser

REPO = Path(__file__).resolve().parents[2]
PHOENIX = REPO / "phoenix"
sys.path.insert(0, str(PHOENIX))
from matrix_gui.modules.vault.crypto.vault_handler import save_vault_singlefile


def fixture():
    return {"deployments": {
        "allowed": {"label": "Synthetic", "name": "demo", "swarm_key": "HIDDEN-SWARM-KEY",
                    "encrypted_bundle": {"vault": "HIDDEN-BUNDLE"},
                    "agents": [{"universal_id": "agent-1", "name": "matrix_ssh", "app": "watch",
                                "connection": {"password": "HIDDEN-PASSWORD", "host": "HIDDEN-HOST"},
                                "config": {"private_key": "HIDDEN-KEY"}}]},
        "unselected": {"label": "Other", "agents": []}},
        "registry": {"secret": "HIDDEN-REGISTRY"}}


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.inventory = console.public_inventory(fixture())
        self.now = 10
        self.access = console.InventoryAccess(self.inventory, ["allowed"], 60, clock=lambda: self.now)

    def test_exact_read_only_surface_and_secret_free_projection(self):
        description = self.access.handle("tools.describe", {})
        self.assertEqual(console.READ_OPERATIONS, {t["name"] for t in description["tools"]})
        self.assertFalse(description["remote_actions_available"])
        outputs = [self.access.handle("deployment.list", {}),
                   self.access.handle("agent.list", {"deployment_id": "allowed"}),
                   self.access.handle("agent.describe", {"deployment_id": "allowed", "agent_id": "agent-1"})]
        self.assertNotIn("HIDDEN", json.dumps(outputs))
        self.assertNotIn("unselected", json.dumps(outputs))
        self.assertEqual([], outputs[-1]["actions"])

    def test_no_aliases_extra_parameters_or_unselected_agents(self):
        cases = [("agent.list", {"deployment_id": "unselected"}),
                 ("agent.list", {"deployment_id": "demo"}),
                 ("agent.describe", {"deployment_id": "allowed", "agent_id": "other"}),
                 ("agent.list", {"deployment_id": "allowed", "credentials": True}),
                 ("deployment.list", {"approve": True})]
        for method, params in cases:
            with self.subTest(method=method, params=params), self.assertRaises((PermissionError, ValueError)):
                self.access.handle(method, params)

    def test_mutations_and_evidence_requests_are_always_denied(self):
        for method in ("deployment.launch", "agent.restart", "agent.config.set", "vault.read", "vault.unlock",
                       "investigation.open", "agent.logs.start", "session.list", "approve", "shell", "deploy"):
            with self.subTest(method=method), self.assertRaises(PermissionError):
                self.access.handle(method, {})

    def test_gui_display_metadata_is_not_terminal_authority(self):
        data = fixture()
        data["ui_preferences"] = {"llm_terminal_fields": True}
        data["registry"] = {"matrix_ssh": {"route": {"meta": {"terminal": {
            "schema_version": 1, "target_server": {"host": "HIDDEN-HOST"},
            "allow_all": True}}}}}
        self.assertEqual(self.inventory, console.public_inventory(data))
        data["ui_preferences"]["llm_terminal_fields"] = False
        self.assertEqual(self.inventory, console.public_inventory(data))
        with self.assertRaises(PermissionError):
            self.access.handle("deployment.launch", {"deployment_id": "allowed"})

    def test_access_expiry_and_explicit_revocation(self):
        self.now = 70
        with self.assertRaises(PermissionError):
            self.access.handle("bridge.status", {})
        self.assertEqual({}, self.access._inventory)
        other = console.InventoryAccess(self.inventory, ["allowed"], 60)
        other.revoke()
        with self.assertRaises(PermissionError):
            other.handle("tools.describe", {})

    def test_snapshot_and_return_values_cannot_mutate_scope(self):
        self.inventory["allowed"]["agents"]["later"] = {"universal_id": "later"}
        result = self.access.handle("agent.list", {"deployment_id": "allowed"})
        result["agents"][0]["name"] = "changed"
        again = self.access.handle("agent.list", {"deployment_id": "allowed"})
        self.assertEqual(["agent-1"], [a["universal_id"] for a in again["agents"]])
        self.assertEqual("matrix_ssh", again["agents"][0]["name"])

    def test_nested_metadata_and_terminal_escape_sequences_do_not_escape(self):
        data = fixture()
        data["deployments"]["allowed"]["label"] = {"password": "HIDDEN"}
        data["deployments"]["allowed"]["agents"][0]["app"] = "\x1b[31m token=HIDDEN"
        projected = console.public_inventory(data)
        self.assertIsNone(projected["allowed"]["deployment"]["label"])
        self.assertNotIn("HIDDEN", json.dumps(projected))
        self.assertNotIn("\x1b", projected["allowed"]["agents"]["agent-1"]["app"])

    def test_invalid_inventory_and_lifetime_fail_closed(self):
        for data in ({"deployments": []}, {"deployments": {"bad": None}},
                     {"deployments": {"bad": {"agents": [{"universal_id": "a"}, {"universal_id": "a"}]}}},
                     {"deployments": {"bad": {"agents": [{"universal_id": "\x1b"}]}}}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                console.public_inventory(data)
        for ids, lifetime in (([], 60), (["unknown"], 60), (["allowed", "allowed"], 60),
                              (["allowed"], 0), (["allowed"], True), (["allowed"], 3601)):
            with self.subTest(ids=ids, lifetime=lifetime), self.assertRaises(ValueError):
                console.InventoryAccess(self.inventory, ids, lifetime)


class OperatorTests(unittest.TestCase):
    def test_transport_cleanup_failure_still_revokes_and_discards_inventory(self):
        from unittest.mock import Mock
        session = console.OperatorSession(console.public_inventory(fixture()), Path("not-created"))
        session.select(["allowed"])
        access = console.InventoryAccess(session.inventory, session.selected, 60)
        session._access = access
        session._server = Mock()
        session._server.stop.side_effect = OSError("synthetic cleanup failure")
        with self.assertRaises(OSError):
            session.close()
        self.assertFalse(session.inventory)
        self.assertFalse(session.selected)
        with self.assertRaises(PermissionError):
            access.handle("deployment.list", {})

    def test_loopback_scope_reselection_expiry_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            session = console.OperatorSession(console.public_inventory(fixture()), directory)
            try:
                self.assertFalse((directory / "bridge.json").exists())
                with self.assertRaises(ValueError):
                    session.enable(60)
                session.select(["allowed"])
                session.enable(60)
                first_access = session._access
                result = call_bridge(directory, "deployment.list", {})
                self.assertEqual(["allowed"], [d["id"] for d in result["deployments"]])
                with self.assertRaises(RuntimeError):
                    call_bridge(directory, "deployment.launch", {"deployment_id": "allowed"})
                session.select(["unselected"])
                self.assertFalse((directory / "bridge.json").exists())
                with self.assertRaises(PermissionError):
                    first_access.handle("bridge.status", {})
                session.enable(60)
                session._expire(first_access)  # stale timer cannot close the replacement
                self.assertTrue((directory / "bridge.json").exists())
                session._expire(session._access)
                self.assertFalse((directory / "bridge.json").exists())
            finally:
                session.close()
            self.assertEqual({}, session.inventory)

    def test_headless_crypto_roundtrip_has_no_qt_and_does_not_modify_vault(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.json"
            with contextlib.redirect_stdout(io.StringIO()):
                save_vault_singlefile(fixture(), "synthetic-test-only", str(path))
            before = path.read_bytes()
            # Real fresh interpreter: no Qt/display or cockpit startup imports.
            script = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from phoenix_terminal.vault_console import load_inventory
inventory = load_inventory(Path(sys.argv[2]), Path(sys.argv[3]), 'synthetic-test-only')
assert not any(n.startswith(('PyQt', 'PySide')) for n in sys.modules)
assert 'matrix_gui.modules.vault.services.vault_core_singleton' not in sys.modules
print(json.dumps(inventory))
"""
            process = subprocess.run([sys.executable, "-I", "-B", "-c", script,
                                      str(REPO / "phoenix_terminal"), str(PHOENIX), str(path)],
                                     capture_output=True, encoding="utf-8", timeout=15)
            self.assertEqual(0, process.returncode, process.stderr)
            self.assertNotIn("HIDDEN", process.stdout)
            self.assertIn("allowed", json.loads(process.stdout))
            self.assertEqual(before, path.read_bytes())
            self.assertEqual([path], list(path.parent.iterdir()))
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                console.load_inventory(PHOENIX, path, "wrong-test-password")

    def test_piped_input_and_visible_password_fallback_are_refused(self):
        with patch.object(console.sys.stdin, "isatty", return_value=False), \
             patch.object(console.getpass, "getpass") as prompt, self.assertRaises(ValueError):
            console.run_console(PHOENIX, Path("not-read"), Path("not-created"))
        prompt.assert_not_called()
        def insecure_prompt(*args):
            warnings.warn("Cannot hide input", console.getpass.GetPassWarning)
        with patch.object(console.sys.stdin, "isatty", return_value=True), \
             patch.object(console.sys.stderr, "isatty", return_value=True), \
             patch.object(console.getpass, "getpass", side_effect=insecure_prompt), \
             patch.object(console, "load_inventory") as loader, self.assertRaises(RuntimeError):
            console.run_console(PHOENIX, Path("not-read"), Path("not-created"))
        loader.assert_not_called()

    def test_interactive_default_off_confirmation_and_finally_revoke(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            commands = iter(["deployments", "enable", "select allowed", "enable 60", "NO", "enable 60", "ENABLE", "lock"])
            def entered(prompt):
                word = next(commands)
                if word == "lock":
                    self.assertTrue((directory / "bridge.json").exists())
                elif word == "ENABLE":
                    self.assertFalse((directory / "bridge.json").exists())
                return word
            output = io.StringIO()
            with patch.object(console.sys.stdin, "isatty", return_value=True), \
                 patch.object(console.sys.stderr, "isatty", return_value=True), \
                 patch.object(console.getpass, "getpass", return_value="synthetic-test-only"), \
                 patch.object(console, "load_inventory", return_value=console.public_inventory(fixture())), \
                 patch("builtins.input", side_effect=entered), contextlib.redirect_stdout(output):
                self.assertEqual(0, console.run_console(PHOENIX, directory / "not-read", directory))
            self.assertFalse((directory / "bridge.json").exists())
            self.assertNotIn("synthetic-test-only", output.getvalue())
            self.assertNotIn("HIDDEN", output.getvalue())
            self.assertIn("Not enabled", output.getvalue())

    def test_cli_has_no_password_or_unattended_approval_options(self):
        parser = build_parser()
        command = ["vault", "open", "--phoenix-root", str(PHOENIX), "--vault", "test-vault.json"]
        self.assertEqual("vault", parser.parse_args(command).command)
        for option in ("--password", "--password-file", "--yes", "--allow-deploy"):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(command + [option, "no"])
