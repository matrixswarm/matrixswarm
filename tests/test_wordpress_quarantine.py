"""Guard quarantine must report failures and preserve the source plugin."""
import ast
try:
    import fcntl
except ImportError:
    fcntl = None
from functools import wraps
import threading
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "matrixos/agents/python_core/wordpress_plugin_guard/wordpress_plugin_guard.py"
module = ast.parse(SOURCE.read_text(encoding="utf-8"))
agent = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "Agent")
methods = [node for node in agent.body if isinstance(node, ast.FunctionDef) and node.name in {"_quarantine", "_scan_plugins"}]
helpers = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in {"_serialize_manifest", "_safe_component", "_safe_child", "_reject_linked_tree", "_raise_walk_error", "_read_baseline"}]
namespace = {"wraps": wraps, "fcntl": fcntl, "os": os, "shutil": shutil, "time": time, "json": json, "stat": stat}
exec(compile(ast.Module(body=helpers + methods, type_ignores=[]), str(SOURCE), "exec"), namespace)


class Guard:
    _quarantine = namespace["_quarantine"]
    _scan_plugins = namespace["_scan_plugins"]

    def __init__(self, quarantine):
        self._manifest_lock = threading.RLock()
        self.quarantine_dir = str(quarantine)

    def _ensure_dir(self, path):
        os.makedirs(path, exist_ok=True)

    def log(self, *args, **kwargs):
        pass

    def _load_manifest(self):
        return {"tracked_plugins": {}, "untracked_plugins": {}}

    def _normalize_folder_name(self, folder):
        return folder.split("_")[0] or folder

    def should_alert(self, key):
        return True

    def drop_alert(self, info):
        self.alerts.append(info)


class WordpressQuarantineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plugin = self.root / "plugins" / "test-plugin"
        self.plugin.mkdir(parents=True)
        (self.plugin / "fixture.txt").write_text("fixture", encoding="utf-8")
        self.guard = Guard(self.root / "quarantine")
        self.guard.plugin_dir = str(self.plugin.parent)
        self.guard.snapshot_root = str(self.root / "snapshots")
        self.guard.site_id = "site1"
        self.guard.block_new = False
        self.guard.enforce = True
        self.guard.alerts = []

    def test_success_moves_plugin(self):
        self.guard._quarantine("test-plugin", str(self.plugin))
        self.assertFalse(self.plugin.exists())
        self.assertEqual(len(list((self.root / "quarantine").glob("test-plugin_*/fixture.txt"))), 1)

    def test_quarantine_directory_denied_propagates(self):
        with patch.object(self.guard, "_ensure_dir", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.guard._quarantine("test-plugin", str(self.plugin))
        self.assertTrue(self.plugin.exists())

    def test_move_and_fallback_failure_propagates(self):
        with patch.object(shutil, "move", side_effect=PermissionError("denied")), \
                patch.object(shutil, "copytree", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(RuntimeError, "Could not quarantine"):
                self.guard._quarantine("test-plugin", str(self.plugin))
        self.assertTrue(self.plugin.exists())

    def test_failed_block_new_delete_falls_back_to_quarantine(self):
        self.guard.block_new = True
        with patch.object(shutil, "rmtree", side_effect=PermissionError("denied")):
            self.guard._scan_plugins()
        self.assertFalse(self.plugin.exists())
        self.assertEqual(self.guard.alerts[0]["action"], "auto_quarantine")

    def test_scan_reports_failed_quarantine_once(self):
        with patch.object(self.guard, "_quarantine", side_effect=PermissionError("denied")) as quarantine:
            self.guard._scan_plugins()
        quarantine.assert_called_once()
        self.assertTrue(self.plugin.exists())
        self.assertEqual(self.guard.alerts[0]["action"], "quarantine_failed")

    def test_scan_preserves_and_alerts_for_incomplete_approval(self):
        manifest = {"tracked_plugins": {}, "untracked_plugins": {},
                    "pending_approvals": {"test-plugin": "test-plugin"}}
        with patch.object(self.guard, "_load_manifest", return_value=manifest):
            self.guard._scan_plugins()
        self.assertTrue(self.plugin.exists(), "pending approval must not trigger destructive enforcement")
        self.assertIn("pending_approval", [item.get("action") for item in self.guard.alerts])

    def test_scan_alerts_for_pending_plugin_that_is_missing(self):
        self.guard.enforce = False
        manifest = {"tracked_plugins": {}, "untracked_plugins": {},
                    "pending_approvals": {"missing": "missing"}}
        with patch.object(self.guard, "_load_manifest", return_value=manifest):
            self.guard._scan_plugins()
        self.assertTrue(any(item.get("action") == "pending_approval" and item.get("plugin") == "missing"
                            for item in self.guard.alerts))

    def test_scan_alerts_for_symlink_and_still_processes_other_plugins(self):
        try:
            (self.plugin.parent / "linked").symlink_to(self.root, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symbolic link creation unavailable: {type(exc).__name__}")
        self.guard._scan_plugins()
        self.assertFalse(self.plugin.exists())
        self.assertIn("linked_plugin", [item.get("action") for item in self.guard.alerts])
        self.assertIn("auto_quarantine", [item.get("action") for item in self.guard.alerts])

    def test_scan_does_not_drop_folders_with_same_normalized_name(self):
        shutil.rmtree(self.plugin)
        for name in ("example_1", "example_2"):
            (self.plugin.parent / name).mkdir()
        self.guard._scan_plugins()
        self.assertFalse((self.plugin.parent / "example_1").exists())
        self.assertFalse((self.plugin.parent / "example_2").exists())
        self.assertEqual(len(list((self.root / "quarantine").iterdir())), 2)

    def test_collision_with_trusted_baseline_is_reported_without_removal(self):
        shutil.rmtree(self.plugin)
        for name in ("example_1", "example_2"):
            (self.plugin.parent / name).mkdir()
        site = self.root / "snapshots" / "site1"
        site.mkdir(parents=True)
        (site / "example.json").write_text("{}", encoding="utf-8")
        self.guard._scan_plugins()
        self.assertTrue((self.plugin.parent / "example_1").is_dir())
        self.assertTrue((self.plugin.parent / "example_2").is_dir())
        self.assertEqual([a["action"] for a in self.guard.alerts], ["baseline_collision", "baseline_collision"])

    def test_linked_or_malformed_baseline_is_not_trusted(self):
        site = self.root / "snapshots" / "site1"
        site.mkdir(parents=True)
        (site / "test-plugin.json").write_text("not json", encoding="utf-8")
        self.guard._scan_plugins()
        self.assertTrue(self.plugin.exists())
        self.assertIn("unsafe_baseline", [a.get("action") for a in self.guard.alerts])
        self.assertNotIn("auto_quarantine", [a.get("action") for a in self.guard.alerts])

    def test_linked_baseline_is_not_trusted(self):
        site = self.root / "snapshots" / "site1"
        site.mkdir(parents=True)
        target = self.root / "outside.json"
        target.write_text("{}", encoding="utf-8")
        try:
            (site / "test-plugin.json").symlink_to(target)
        except OSError as exc:
            self.skipTest(f"symbolic link creation unavailable: {type(exc).__name__}")
        self.guard._scan_plugins()
        self.assertTrue(target.exists())
        self.assertTrue(self.plugin.exists())
        self.assertIn("unsafe_baseline", [a.get("action") for a in self.guard.alerts])

    def test_baseline_without_exact_approval_is_reported_not_trusted(self):
        site = self.root / "snapshots" / "site1"
        site.mkdir(parents=True)
        (site / "test-plugin.json").write_text("{}", encoding="utf-8")
        self.guard._scan_plugins()
        self.assertTrue(self.plugin.exists())
        self.assertIn("unregistered_baseline", [a.get("action") for a in self.guard.alerts])

    def test_matching_approval_and_valid_baseline_are_not_reported(self):
        site = self.root / "snapshots" / "site1"
        site.mkdir(parents=True)
        (site / "test-plugin.json").write_text("{}", encoding="utf-8")
        record = {"tracked_plugins": {"test-plugin": {"normalized": "test-plugin", "manifest_file": "test-plugin.json"}}, "untracked_plugins": {}}
        with patch.object(self.guard, "_load_manifest", return_value=record):
            self.guard._scan_plugins()
        self.assertTrue(self.plugin.exists())
        self.assertEqual(self.guard.alerts, [])
