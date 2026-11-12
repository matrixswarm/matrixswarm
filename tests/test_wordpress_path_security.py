"""Untrusted RPC names must not escape the guard's managed directories."""
import ast
try:
    import fcntl
except ImportError:
    fcntl = None
from functools import wraps
import threading
import os
import stat
from pathlib import Path
import shutil
import tempfile
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "matrixos/agents/python_core/wordpress_plugin_guard/wordpress_plugin_guard.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"_serialize_manifest", "_safe_component", "_safe_child", "_reject_linked_tree", "_raise_walk_error"}]
agent = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Agent")
names = {"_normalize_folder_name", "cmd_snapshot_plugin", "cmd_disapprove_plugin", "cmd_quarantine_plugin", "cmd_delete_quarantined_plugin", "cmd_restore_plugin"}
methods = [n for n in agent.body if isinstance(n, ast.FunctionDef) and n.name in names]
scope = {"wraps": wraps, "fcntl": fcntl, "stat": stat, "os": os, "shutil": shutil, "time": time}
exec(compile(ast.Module(body=helpers + methods, type_ignores=[]), str(SOURCE), "exec"), scope)


class Guard:
    _normalize_folder_name = scope["_normalize_folder_name"]
    cmd_snapshot_plugin = scope["cmd_snapshot_plugin"]
    cmd_disapprove_plugin = scope["cmd_disapprove_plugin"]
    cmd_quarantine_plugin = scope["cmd_quarantine_plugin"]
    cmd_delete_quarantined_plugin = scope["cmd_delete_quarantined_plugin"]
    cmd_restore_plugin = scope["cmd_restore_plugin"]

    def __init__(self, root):
        self._manifest_lock = threading.RLock()
        self.plugin_dir = str(root / "plugins")
        self.quarantine_dir = str(root / "quarantine")
        self.snapshot_root = str(root / "snapshots")
        self.site_id = "site1"
        self.manifest = {"tracked_plugins": {}, "untracked_plugins": {}}
        self.snapshots = []

    def log(self, *args, **kwargs):
        pass

    def _ensure_dir(self, path):
        os.makedirs(path, exist_ok=True)

    def _load_manifest(self):
        return self.manifest

    def _save_manifest(self, manifest):
        self.manifest = manifest

    def _snapshot_plugin(self, path, manifest):
        self.snapshots.append((path, manifest))

    def _register_plugin(self, manifest, plugin, normalized):
        manifest["tracked_plugins"][plugin] = {"normalized": normalized}

    def _begin_approval(self, plugin, normalized):
        self.manifest.setdefault("pending_approvals", {})[normalized] = plugin

    def _finish_approval(self, plugin, normalized):
        self._register_plugin(self.manifest, plugin, normalized)
        del self.manifest["pending_approvals"][normalized]

    def _cmd_list_alert_status(self, *args):
        pass


class WordpressPathSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for directory in ("plugins", "quarantine", "snapshots/site1", "outside"):
            (self.root / directory).mkdir(parents=True)
        self.victim = self.root / "outside" / "fixture.txt"
        self.victim.write_text("safe", encoding="utf-8")
        self.guard = Guard(self.root)

    def call(self, name, plugin):
        getattr(self.guard, name)(None, {"content": {"plugin": plugin}})

    def test_unreadable_subdirectory_does_not_pass_snapshot_walk(self):
        from unittest.mock import patch
        def fail_walk(_path, **kwargs):
            kwargs["onerror"](PermissionError("denied"))
            yield
        with patch.object(os, "walk", side_effect=fail_walk):
            with self.assertRaises(PermissionError):
                scope["_reject_linked_tree"](str(self.root / "plugins"))

    def test_rpc_commands_reject_escape_components(self):
        commands = ("cmd_snapshot_plugin", "cmd_disapprove_plugin", "cmd_quarantine_plugin", "cmd_delete_quarantined_plugin", "cmd_restore_plugin")
        for command in commands:
            for name in ("../outside", "..", ".", str(self.root / "outside"), "a/b", "a\\b", "x\nfile"):
                with self.subTest(command=command, name=name):
                    self.call(command, name)
                    self.assertTrue(self.victim.exists())
                    self.assertFalse(self.guard.snapshots)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links unavailable")
    def test_rpc_commands_refuse_linked_plugin_and_quarantine(self):
        try:
            (self.root / "plugins" / "linked").symlink_to(self.root / "outside", target_is_directory=True)
            (self.root / "quarantine" / "linked").symlink_to(self.root / "outside", target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symbolic link creation unavailable: {type(exc).__name__}")
        for command in ("cmd_snapshot_plugin", "cmd_quarantine_plugin", "cmd_delete_quarantined_plugin", "cmd_restore_plugin"):
            with self.subTest(command=command):
                self.call(command, "linked")
                self.assertTrue(self.victim.exists())
                self.assertFalse(self.guard.snapshots)

    def test_forged_manifest_name_cannot_delete_outside_snapshot(self):
        outside = self.root / "snapshots" / "outside.json"
        outside.write_text("fixture", encoding="utf-8")
        self.guard.manifest["tracked_plugins"]["valid"] = {"normalized": "../outside"}
        self.call("cmd_disapprove_plugin", "valid")
        self.assertTrue(outside.exists())
        self.assertIn("valid", self.guard.manifest["tracked_plugins"])

    def test_linked_snapshot_directory_cannot_delete_outside_file(self):
        site = self.root / "snapshots" / "site1"
        site.rmdir()
        try:
            site.symlink_to(self.root / "outside", target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symbolic link creation unavailable: {type(exc).__name__}")
        victim = self.root / "outside" / "valid.json"
        victim.write_text("safe", encoding="utf-8")
        self.guard.manifest["tracked_plugins"]["valid"] = {"normalized": "valid"}
        try:
            self.call("cmd_disapprove_plugin", "valid")
        except ValueError:
            pass  # POSIX lock acquisition rejects the linked site before dispatch.
        self.assertTrue(victim.exists())
        self.assertIn("valid", self.guard.manifest["tracked_plugins"])

    def test_snapshot_uses_actual_suffixed_plugin_directory(self):
        source = self.root / "plugins" / "example_1234"
        source.mkdir()
        self.call("cmd_snapshot_plugin", source.name)
        self.assertEqual(len(self.guard.snapshots), 1)
        self.assertEqual(Path(self.guard.snapshots[0][0]), source)

    def test_valid_plugin_can_be_quarantined_and_deleted(self):
        source = self.root / "plugins" / "example"
        source.mkdir()
        (source / "safe.txt").write_text("safe", encoding="utf-8")
        self.call("cmd_quarantine_plugin", "example")
        self.assertFalse(source.exists())
        quarantined = list((self.root / "quarantine").glob("example_*"))
        self.assertEqual(len(quarantined), 1)
        self.call("cmd_delete_quarantined_plugin", quarantined[0].name)
        self.assertFalse(quarantined[0].exists())
        self.assertTrue(self.victim.exists())

    def test_valid_quarantined_plugin_restores_and_snapshots(self):
        source = self.root / "quarantine" / "example_1234"
        source.mkdir()
        (source / "safe.txt").write_text("safe", encoding="utf-8")
        self.call("cmd_restore_plugin", source.name)
        restored = self.root / "plugins" / "example"
        self.assertTrue((restored / "safe.txt").exists())
        self.assertFalse(source.exists())
        self.assertEqual(Path(self.guard.snapshots[0][0]), restored)
        self.assertIn("example", self.guard.manifest["tracked_plugins"])

    def test_read_only_blocks_manual_quarantine_delete_and_restore(self):
        source = self.root / "plugins" / "example"
        source.mkdir()
        quarantined = self.root / "quarantine" / "other_123"
        quarantined.mkdir()
        (quarantined / "safe.txt").write_text("safe", encoding="utf-8")
        self.guard.read_only = True
        self.call("cmd_quarantine_plugin", "example")
        self.call("cmd_delete_quarantined_plugin", "other_123")
        self.call("cmd_restore_plugin", "other_123")
        self.assertTrue(source.is_dir())
        self.assertTrue((quarantined / "safe.txt").exists())
        self.assertFalse((self.root / "plugins" / "other").exists())

    def test_nested_symlink_is_rejected_before_snapshot(self):
        plugin = self.root / "plugins" / "example"
        plugin.mkdir()
        try:
            (plugin / "linked-file").symlink_to(self.victim)
        except OSError as exc:
            self.skipTest(f"symbolic link creation unavailable: {type(exc).__name__}")
        with self.assertRaises(ValueError):
            scope["_reject_linked_tree"](str(plugin))
