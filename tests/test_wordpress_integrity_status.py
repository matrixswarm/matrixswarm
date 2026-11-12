"""A broken plugin must not hide other integrity results in the panel."""
import ast
try:
    import fcntl
except ImportError:
    fcntl = None
from functools import wraps
import threading
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import shutil
import tempfile
import time
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "matrixos/agents/python_core/wordpress_plugin_guard/wordpress_plugin_guard.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
helper_names = {"_serialize_manifest", "_safe_component", "_safe_child", "_raise_walk_error", "_read_baseline", "_reject_linked_tree"}
helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in helper_names]
agent = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Agent")
method_names = {"_normalize_folder_name", "_sha256_file", "_compare_plugin", "_scan_plugins", "_cmd_list_alert_status"}
methods = [node for node in agent.body if isinstance(node, ast.FunctionDef) and node.name in method_names]
scope = {"wraps": wraps, "fcntl": fcntl, "os": os, "json": json, "hashlib": hashlib, "stat": stat, "time": time, "shutil": shutil}
exec(compile(ast.Module(body=helpers + methods, type_ignores=[]), str(SOURCE), "exec"), scope)


class Guard:
    _normalize_folder_name = scope["_normalize_folder_name"]
    _sha256_file = scope["_sha256_file"]
    _compare_plugin = scope["_compare_plugin"]
    _scan_plugins = scope["_scan_plugins"]
    _cmd_list_alert_status = scope["_cmd_list_alert_status"]

    def __init__(self, root):
        self._manifest_lock = threading.RLock()
        self.plugin_dir = str(root / "plugins")
        self.snapshot_root = str(root / "snapshots")
        self.quarantine_dir = str(root / "quarantine")
        self.site_id = "site1"
        self.block_new = False
        self.enforce = False
        self.read_only = False
        self.manifest = {"tracked_plugins": {}, "untracked_plugins": {}}
        self.output = None
        self.alerts = []
        self._quarantine = Mock()

    def _ensure_dir(self, path):
        os.makedirs(path, exist_ok=True)

    def _load_manifest(self):
        return deepcopy(self.manifest)

    def _save_manifest(self, manifest):
        self.manifest = deepcopy(manifest)

    def _broadcast_output(self, output, **kwargs):
        self.output = output

    def log(self, *args, **kwargs):
        pass

    def should_alert(self, key):
        return True

    def drop_alert(self, info):
        self.alerts.append(info)


class WordpressIntegrityStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "plugins").mkdir()
        (self.root / "snapshots" / "site1").mkdir(parents=True)
        (self.root / "quarantine").mkdir()
        self.guard = Guard(self.root)

    def add_tracked(self, name):
        directory = self.root / "plugins" / name
        directory.mkdir()
        (directory / "fixture.php").write_text("safe", encoding="utf-8")
        baseline = {"fixture.php": hashlib.sha256(b"safe").hexdigest()}
        (self.root / "snapshots" / "site1" / f"{name}.json").write_text(json.dumps(baseline), encoding="utf-8")
        self.guard.manifest["tracked_plugins"][name] = {"normalized": name, "manifest_file": f"{name}.json"}
        return directory

    def test_corrupt_and_unreadable_tracked_plugins_do_not_hide_other_results(self):
        self.add_tracked("healthy")
        self.add_tracked("corrupt")
        denied = self.add_tracked("denied")
        (self.root / "snapshots" / "site1" / "corrupt.json").write_text("not JSON", encoding="utf-8")
        (self.root / "plugins" / "new-plugin").mkdir()
        real_walk = os.walk
        def walk(path, *args, **kwargs):
            if Path(path) == denied:
                kwargs["onerror"](PermissionError("fixture denied"))
            return real_walk(path, *args, **kwargs)
        with patch.object(os, "walk", side_effect=walk):
            self.guard._cmd_list_alert_status()
        output = self.guard.output
        self.assertIsNotNone(output, "integrity errors must not suppress the entire panel response")
        self.assertIn("healthy", output["tracked_clean"])
        self.assertIn("new-plugin", output["untracked"])
        for name in ("corrupt", "denied"):
            with self.subTest(plugin=name):
                self.assertIn(name, output["tracked_alerts"])
                self.assertTrue(output["tracked_alerts"][name]["reason"])
                self.assertNotIn(name, output["tracked_clean"])

    def test_tracked_and_untracked_symlinks_are_alerts_not_clean(self):
        self.add_tracked("healthy")
        outside = self.root / "outside"
        outside.mkdir()
        try:
            (self.root / "plugins" / "linked-tracked").symlink_to(outside, target_is_directory=True)
            (self.root / "plugins" / "linked-untracked").symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symbolic link creation unavailable: {type(exc).__name__}")
        self.guard.manifest["tracked_plugins"]["linked-tracked"] = {"normalized": "linked-tracked"}
        self.guard._cmd_list_alert_status()
        output = self.guard.output
        self.assertIsNotNone(output)
        self.assertIn("healthy", output["tracked_clean"])
        for name in ("linked-tracked", "linked-untracked"):
            with self.subTest(plugin=name):
                self.assertIn(name, output["tracked_alerts"])
                self.assertTrue(output["tracked_alerts"][name]["reason"])
                self.assertNotIn(name, output["tracked_clean"])

    def test_pending_approval_is_alert_for_tracked_and_untracked_plugin(self):
        self.add_tracked("healthy")
        self.add_tracked("pending-tracked")
        (self.root / "plugins" / "pending-untracked").mkdir()
        self.guard.manifest["pending_approvals"] = {
            "pending-tracked": "pending-tracked", "pending-untracked": "pending-untracked"
        }
        self.guard._cmd_list_alert_status()
        output = self.guard.output
        self.assertIn("healthy", output["tracked_clean"])
        for plugin in ("pending-tracked", "pending-untracked"):
            with self.subTest(plugin=plugin):
                self.assertIn(plugin, output["tracked_alerts"])
                self.assertIn("approval", output["tracked_alerts"][plugin]["reason"].lower())
                self.assertNotIn(plugin, output["tracked_clean"])

    def test_pending_marker_for_absent_plugin_still_visible(self):
        self.guard.manifest["pending_approvals"] = {"absent": "absent"}
        self.guard._cmd_list_alert_status()
        self.assertIn("absent", self.guard.output["tracked_alerts"])

    def test_pending_shared_baseline_marks_every_colliding_folder(self):
        for name in ("example_1", "example_2"):
            (self.root / "plugins" / name).mkdir()
            self.guard.manifest["tracked_plugins"][name] = {"normalized": "example"}
        self.guard.manifest["pending_approvals"] = {"example": "example_1"}
        self.guard._cmd_list_alert_status()
        self.assertEqual(set(self.guard.output["tracked_alerts"]), {"example_1", "example_2"})
        self.assertEqual(self.guard.output["tracked_clean"], [])

    def test_invalid_approval_metadata_is_an_alert(self):
        self.add_tracked("healthy")
        self.guard.manifest["tracked_plugins"]["healthy"]["manifest_file"] = "wrong.json"
        self.guard._cmd_list_alert_status()
        self.assertIn("healthy", self.guard.output["tracked_alerts"])
        self.assertNotIn("healthy", self.guard.output["tracked_clean"])

    def test_periodic_scan_alerts_modified_plugin_without_enforcement(self):
        path = self.add_tracked("healthy")
        (path / "fixture.php").write_text("changed", encoding="utf-8")
        self.guard._scan_plugins()
        self.guard._quarantine.assert_not_called()
        self.assertTrue(path.exists())
        self.assertIn("plugin_modified", [item.get("action") for item in self.guard.alerts])

    def test_periodic_scan_quarantines_verified_change_only_when_enabled(self):
        path = self.add_tracked("healthy")
        (path / "fixture.php").write_text("changed", encoding="utf-8")
        self.guard.enforce = True
        self.guard._scan_plugins()
        self.guard._quarantine.assert_called_once_with("healthy", str(path))
        self.assertIn("auto_quarantine", [item.get("action") for item in self.guard.alerts])

    def test_periodic_scan_does_not_quarantine_modified_plugin_in_read_only_mode(self):
        path = self.add_tracked("healthy")
        (path / "fixture.php").write_text("changed", encoding="utf-8")
        self.guard.enforce = True
        self.guard.read_only = True
        self.guard._scan_plugins()
        self.guard._quarantine.assert_not_called()
        self.assertTrue(path.exists())
        self.assertIn("plugin_modified", [item.get("action") for item in self.guard.alerts])

    def test_periodic_scan_leaves_unverifiable_plugin_even_with_enforcement(self):
        path = self.add_tracked("healthy")
        self.guard.enforce = True
        real_walk = os.walk
        def walk(candidate, *args, **kwargs):
            if Path(candidate) == path:
                kwargs["onerror"](PermissionError("fixture denied"))
            return real_walk(candidate, *args, **kwargs)
        with patch.object(os, "walk", side_effect=walk):
            self.guard._scan_plugins()
        self.guard._quarantine.assert_not_called()
        self.assertTrue(path.exists())
        self.assertIn("integrity_unverifiable", [item.get("action") for item in self.guard.alerts])

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "geteuid"), "POSIX permissions required")
    def test_read_only_monitoring_does_not_write_or_enforce(self):
        if os.geteuid() == 0:
            self.skipTest("must run as an unprivileged user")
        site = self.root / "snapshots" / "site1"
        self.addCleanup(site.chmod, 0o700)
        (self.root / "plugins" / "new-plugin").mkdir()
        self.guard.manifest["tracked_plugins"]["missing"] = {"normalized": "missing", "manifest_file": "missing.json"}
        self.guard.read_only = True
        self.guard.enforce = True
        self.guard.block_new = True
        site.chmod(0o555)
        with patch.object(self.guard, "_save_manifest", side_effect=AssertionError("read-only wrote manifest")):
            self.guard._scan_plugins()
            self.guard._cmd_list_alert_status()
        self.assertTrue((self.root / "plugins" / "new-plugin").exists())
        self.guard._quarantine.assert_not_called()
        self.assertIn("new-plugin", self.guard.output["untracked"])
        self.assertFalse((site / ".approval.lock").exists())

    @unittest.skipIf(fcntl is None, "POSIX directory locks are unavailable")
    def test_read_only_does_not_create_missing_site_directory(self):
        site = self.root / "snapshots" / "site1"
        site.rmdir()
        self.guard.read_only = True
        with self.assertRaises(FileNotFoundError):
            self.guard._cmd_list_alert_status()
        self.assertFalse(site.exists())


if __name__ == "__main__":
    unittest.main()
