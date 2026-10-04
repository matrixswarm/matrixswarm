"""Tripwire must not boot after a partially completed initialization."""

import ast
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
from core.python_core.class_lib.crypto.symmetric_encryption.aes.aes import AESHandlerBytesShim
from core.python_core.class_lib.inotify_events.jedi_event_flow import JediEventFlow


class TripwireStartupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = {
            "quarantine_root": str(self.root / "quarantine"),
            "security": {"symmetric_encryption": {
                "key": base64.b64encode(b"k" * 32).decode("ascii"),
            }},
        }
        self.log = Mock()
        self.beacon = Mock()
        self.register_beacon = Mock(return_value=self.beacon)
        fixture = self

        class BootFixture:
            def __init__(self):
                self.tree_node = {"config": fixture.config}
                self.path_resolution = {"static_comm_path_resolved": str(fixture.root)}
                self.log = fixture.log
                self.check_for_thread_poke = fixture.register_beacon
                self.running = True

        # Load the real class body without starting a Linux process or importing
        # inotify on Windows. Only the boot environment and kernel probe are faked.
        source = ROOT / "matrixos/agents/python_core/tripwire_lite/tripwire_lite.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Agent")
        scope = {
            "BootAgent": BootFixture, "IdentityObject": object,
            "os": SimpleNamespace(path=os.path, sep=os.sep, makedirs=os.makedirs),
            "JediEventFlow": JediEventFlow, "AESHandlerBytesShim": AESHandlerBytesShim,
            "interruptible_sleep": Mock(),
        }
        exec(compile(ast.Module(body=[cls], type_ignores=[]), str(source), "exec"), scope)
        self.Agent = scope["Agent"]
        self.Agent._get_kernel_inotify_limits = lambda _self: (8192, 128)
        self.scope = scope

    def test_quarantine_permission_error_is_not_swallowed(self):
        denied = PermissionError(13, "Permission denied", "/matrix/quarantine")
        with patch.object(self.scope["os"], "makedirs", side_effect=denied):
            with self.assertRaises(PermissionError) as caught:
                self.Agent()
        self.assertIs(caught.exception, denied)
        self.assertIs(self.log.call_args.kwargs["error"], denied)
        self.assertEqual(self.log.call_args.kwargs["level"], "CRITICAL")
        self.register_beacon.assert_not_called()

    def test_invalid_interval_cannot_leave_a_bootable_partial_agent(self):
        self.config["interval"] = "invalid"
        with self.assertRaises(ValueError):
            self.Agent()
        self.register_beacon.assert_not_called()

    def test_detect_only_mode_does_not_create_quarantine(self):
        self.config["enforce"] = False
        with patch.object(self.scope["os"], "makedirs", side_effect=PermissionError) as mkdir:
            agent = self.Agent()
        mkdir.assert_not_called()
        agent.worker()
        self.beacon.assert_called_once_with()

    def test_dry_run_mode_does_not_create_quarantine(self):
        self.config.update(enforce=True, dry_run=True)
        with patch.object(self.scope["os"], "makedirs", side_effect=PermissionError) as mkdir:
            agent = self.Agent()
        mkdir.assert_not_called()
        agent.worker()
        self.beacon.assert_called_once_with()

    def test_encryption_failure_after_beacon_setup_also_stops_initialization(self):
        self.config["security"]["symmetric_encryption"]["key"] = ""
        with self.assertRaisesRegex(ValueError, "base64-encoded key"):
            self.Agent()
        self.assertEqual(self.register_beacon.call_count, 2)
        self.beacon.assert_not_called()

    def test_successful_initialization_provides_both_beacons(self):
        agent = self.Agent()
        self.assertTrue((self.root / "quarantine").is_dir())
        self.assertIs(agent._emit_beacon, self.beacon)
        self.assertIs(agent._emit_beacon_trip_guard, self.beacon)
        agent.worker()
        self.beacon.assert_called_once_with()
        self.scope["interruptible_sleep"].assert_called_once_with(agent, 5)

    def test_legacy_shared_default_uses_owned_static_storage(self):
        self.config.update(quarantine_root="/matrix/quarantine", enforce=True, dry_run=False)
        real_mkdir = os.makedirs

        def owned_only(path, **kwargs):
            if path == "/matrix/quarantine":
                raise PermissionError(13, "Permission denied", path)
            return real_mkdir(path, **kwargs)

        with patch.object(self.scope["os"], "makedirs", side_effect=owned_only) as mkdir:
            agent = self.Agent()
        expected = str(self.root / "quarantine")
        self.assertEqual(agent._quarantine_root, expected)
        mkdir.assert_called_once_with(expected, mode=0o700, exist_ok=True)
        self.assertTrue(Path(expected).is_dir())
        agent.worker()
        self.beacon.assert_called_once_with()

    def test_automatic_settings_resolve_beneath_agent_static_path(self):
        for setting in (None, "", "   ", "/matrix/quarantine", "/matrix/quarantine/"):
            with self.subTest(setting=setting):
                self.config["quarantine_root"] = setting
                agent = self.Agent()
                self.assertEqual(agent._quarantine_root, str(self.root / "quarantine"))
        del self.config["quarantine_root"]
        self.assertEqual(self.Agent()._quarantine_root, str(self.root / "quarantine"))

    def test_new_template_requests_automatic_storage(self):
        template = json.loads((ROOT / "phoenix/agents_meta/tripwire_lite.json").read_text(encoding="utf-8"))
        self.assertEqual(template["config"]["quarantine_root"], "")

    def test_custom_path_is_preserved(self):
        custom = self.root / "custom-quarantine"
        self.config["quarantine_root"] = str(custom)
        self.assertEqual(self.Agent()._quarantine_root, str(custom))
        self.assertTrue(custom.is_dir())

    def test_invalid_quarantine_path_stops_initialization(self):
        for value in (False, 17, [], {}):
            with self.subTest(value=value):
                self.config["quarantine_root"] = value
                with self.assertRaisesRegex(ValueError, "quarantine_root"):
                    self.Agent()

    def test_agent_never_reprocesses_its_quarantine(self):
        self.config["quarantine_root"] = ""
        agent = self.Agent()
        self.assertTrue(agent._is_ignored(str(self.root / "quarantine")))
        self.assertTrue(agent._is_ignored(str(self.root / "quarantine" / "timestamp" / "file.php")))
        self.assertFalse(agent._is_ignored(str(self.root / "quarantine-neighbor" / "file.php")))


if __name__ == "__main__":
    unittest.main()
