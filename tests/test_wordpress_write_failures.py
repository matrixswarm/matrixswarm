"""Exercise WordPress Guard's actual write helpers under failure conditions."""
import ast
try:
    import fcntl
except ImportError:
    fcntl = None
from functools import wraps
import threading
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import stat
import tempfile
import time
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "matrixos/agents/python_core/wordpress_plugin_guard/wordpress_plugin_guard.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
helper_names = {"_serialize_manifest", "_safe_component", "_safe_child", "_raise_walk_error", "_atomic_write_json", "_reject_linked_tree", "_read_baseline"}
helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in helper_names]
agent = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Agent")
method_names = {"_ensure_dir", "_safe_write", "_snapshot_plugin", "_snapshot_all_plugins", "_manifest_path", "_load_manifest", "_save_manifest", "_begin_approval", "_finish_approval", "_normalize_folder_name", "_register_plugin", "_sha256_file", "cmd_snapshot_plugin", "cmd_snapshot_untracked", "cmd_restore_plugin", "_cmd_list_alert_status"}
methods = [node for node in agent.body if isinstance(node, ast.FunctionDef) and node.name in method_names]
scope = {"wraps": wraps, "fcntl": fcntl, "os": os, "json": json, "hashlib": hashlib, "stat": stat, "tempfile": tempfile, "time": time, "shutil": shutil}
exec(compile(ast.Module(body=helpers + methods, type_ignores=[]), str(SOURCE), "exec"), scope)


def hold_approval_lock(path, ready, release):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        ready.set()
        release.wait(5)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


class Guard:
    _ensure_dir = scope["_ensure_dir"]
    _safe_write = scope["_safe_write"]
    _snapshot_plugin = scope["_snapshot_plugin"]
    _snapshot_all_plugins = scope["_snapshot_all_plugins"]
    _manifest_path = scope["_manifest_path"]
    _load_manifest = scope["_load_manifest"]
    _save_manifest = scope["_save_manifest"]
    _begin_approval = scope["_begin_approval"]
    _finish_approval = scope["_finish_approval"]
    _normalize_folder_name = scope["_normalize_folder_name"]
    _register_plugin = scope["_register_plugin"]
    _sha256_file = scope["_sha256_file"]
    cmd_snapshot_plugin = scope["cmd_snapshot_plugin"]
    cmd_snapshot_untracked = scope["cmd_snapshot_untracked"]
    cmd_restore_plugin = scope["cmd_restore_plugin"]

    def __init__(self, root):
        self._manifest_lock = threading.RLock()
        self.plugin_dir = str(root / "plugins")
        self.snapshot_root = str(root / "snapshots")
        self.quarantine_dir = str(root / "quarantine")
        self.site_id = "site1"
        self.read_only = False
        self.enforce = False
        self.block_new = False
        self.logs = []
        self.alerts = []
        self.refresh = Mock()
        self.broadcast = Mock()

    def log(self, *args, **kwargs):
        self.logs.append((args, kwargs))

    def drop_alert(self, info):
        self.alerts.append(info)

    def _cmd_list_alert_status(self, *args):
        self.refresh(*args)

    def _broadcast_output(self, *args, **kwargs):
        self.broadcast(*args, **kwargs)


class WordpressWriteFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plugin = self.root / "plugins" / "example"
        self.plugin.mkdir(parents=True)
        (self.plugin / "plugin.php").write_text("fixture", encoding="utf-8")
        self.site = self.root / "snapshots" / "site1"
        self.site.mkdir(parents=True)
        self.guard = Guard(self.root)

    def approve(self):
        self.guard.cmd_snapshot_plugin(None, {"content": {"plugin": "example"}})

    def assert_not_approved(self):
        self.assertNotIn("example", self.guard._load_manifest()["tracked_plugins"])
        self.assertFalse(any("Approved plugin" in str(args) for args, _ in self.guard.logs))
        self.guard.refresh.assert_not_called()

    def test_real_ensure_dir_propagates_permission_failure(self):
        with patch.object(os, "makedirs", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.guard._ensure_dir(str(self.root / "not-created"))

    def test_real_safe_write_fails_closed_for_read_only_and_io_errors(self):
        writer = Mock()
        self.guard.read_only = True
        with self.assertRaises(PermissionError):
            self.guard._safe_write("fixture", writer)
        writer.assert_not_called()
        self.guard.read_only = False
        for error, action in ((PermissionError("denied"), "permission_error"), (OSError(28, "full"), "write_failed")):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(type(error)):
                    self.guard._safe_write("fixture", Mock(side_effect=error))
                self.assertEqual(self.guard.alerts[-1]["action"], action)

    def test_linked_manifest_is_neither_read_nor_overwritten(self):
        outside = self.root / "outside.json"
        outside.write_text('{"sentinel": true}', encoding="utf-8")
        try:
            (self.site / ".manifest.json").symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"symbolic link creation unavailable: {type(exc).__name__}")
        with self.assertRaises(ValueError):
            self.guard._load_manifest()
        with self.assertRaises(ValueError):
            self.guard._save_manifest({"tracked_plugins": {}})
        self.assertEqual(json.loads(outside.read_text(encoding="utf-8")), {"sentinel": True})

    def test_successful_manifest_save_is_readable_without_temp_files(self):
        manifest = {"tracked_plugins": {"example": {"normalized": "example"}}, "untracked_plugins": {}}
        self.guard._save_manifest(manifest)
        self.assertEqual(self.guard._load_manifest()["tracked_plugins"], manifest["tracked_plugins"])
        self.assertFalse(list(self.site.glob(".plugin-guard-*")))

    @unittest.skipUnless(os.name == "posix", "directory fsync is a POSIX durability check")
    def test_manifest_commit_syncs_file_and_directory(self):
        sync = os.fsync
        with patch.object(os, "fsync", wraps=sync) as fsync:
            self.guard._save_manifest({"tracked_plugins": {}, "untracked_plugins": {}})
        self.assertGreaterEqual(fsync.call_count, 2)

    def test_failed_atomic_replace_preserves_previous_manifest(self):
        path = self.site / ".manifest.json"
        original = {"tracked_plugins": {"old": {"normalized": "old"}}, "untracked_plugins": {}}
        path.write_text(json.dumps(original), encoding="utf-8")
        with patch.object(os, "replace", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.guard._save_manifest({"tracked_plugins": {"new": {}}})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)
        self.assertFalse(list(self.site.glob(".plugin-guard-*")))

    def test_successful_snapshot_saves_baseline_before_approval(self):
        self.approve()
        baseline = json.loads((self.site / "example.json").read_text(encoding="utf-8"))
        self.assertEqual(baseline["plugin.php"], hashlib.sha256(b"fixture").hexdigest())
        self.assertIn("example", self.guard._load_manifest()["tracked_plugins"])
        self.assertEqual(self.guard._load_manifest().get("pending_approvals", {}), {})
        self.assertTrue(any("Approved plugin" in str(args) for args, _ in self.guard.logs))
        self.guard.refresh.assert_called_once()

    def test_failed_baseline_write_never_approves_plugin(self):
        write = scope["_atomic_write_json"]
        def fail_baseline(path, payload):
            if Path(path).name == "example.json":
                raise PermissionError("denied")
            return write(path, payload)
        with patch.dict(scope, {"_atomic_write_json": fail_baseline}):
            self.approve()
        self.assert_not_approved()
        self.assertEqual(self.guard._load_manifest()["pending_approvals"], {"example": "example"})
        self.assertEqual(self.guard.alerts[-1]["action"], "permission_error")

    def test_failed_manifest_write_never_reports_approval(self):
        write = scope["_atomic_write_json"]
        manifest_writes = 0
        def fail_manifest(path, payload):
            nonlocal manifest_writes
            if Path(path).name == ".manifest.json":
                manifest_writes += 1
                if manifest_writes == 2:
                    raise PermissionError("denied")
            return write(path, payload)
        with patch.dict(scope, {"_atomic_write_json": fail_manifest}):
            self.approve()
        self.assert_not_approved()
        self.assertTrue((self.site / "example.json").exists())
        self.assertEqual(self.guard._load_manifest()["pending_approvals"], {"example": "example"})
        self.assertEqual(self.guard.alerts[-1]["action"], "permission_error")

    def test_failed_reapproval_keeps_pending_even_with_a_prior_trusted_record(self):
        self.approve()
        self.guard.logs.clear()
        self.guard.refresh.reset_mock()
        (self.plugin / "plugin.php").write_text("changed", encoding="utf-8")
        write = scope["_atomic_write_json"]
        manifest_writes = 0
        def fail_finish(path, payload):
            nonlocal manifest_writes
            if Path(path).name == ".manifest.json":
                manifest_writes += 1
                if manifest_writes == 2:
                    raise PermissionError("denied")
            return write(path, payload)
        with patch.dict(scope, {"_atomic_write_json": fail_finish}):
            self.approve()
        manifest = self.guard._load_manifest()
        self.assertIn("example", manifest["tracked_plugins"])
        self.assertEqual(manifest["pending_approvals"], {"example": "example"})
        self.assertFalse(any("Approved plugin" in str(args) for args, _ in self.guard.logs))
        self.guard.refresh.assert_not_called()
        # Exercise the real panel-status method against the persisted marker.
        scope["_cmd_list_alert_status"](self.guard)
        output = self.guard.broadcast.call_args.args[0]
        self.assertIn("example", output["tracked_alerts"])
        self.assertNotIn("example", output["tracked_clean"])

    def test_pending_approval_can_be_retried_successfully(self):
        self.guard._begin_approval("example", "example")
        self.approve()
        manifest = self.guard._load_manifest()
        self.assertIn("example", manifest["tracked_plugins"])
        self.assertEqual(manifest["pending_approvals"], {})

    def test_bulk_refresh_failure_keeps_prior_approval_pending(self):
        self.approve()
        (self.plugin / "plugin.php").write_text("changed", encoding="utf-8")
        write = scope["_atomic_write_json"]
        manifest_writes = 0
        def fail_finish(path, payload):
            nonlocal manifest_writes
            if Path(path).name == ".manifest.json":
                manifest_writes += 1
                if manifest_writes == 2:
                    raise PermissionError("denied")
            return write(path, payload)
        with patch.dict(scope, {"_atomic_write_json": fail_finish}):
            with self.assertRaises(PermissionError):
                self.guard._snapshot_all_plugins()
        self.assertEqual(self.guard._load_manifest()["pending_approvals"], {"example": "example"})

    def test_untracked_bulk_failure_leaves_pending_and_no_success_reply(self):
        write = scope["_atomic_write_json"]
        manifest_writes = 0
        def fail_finish(path, payload):
            nonlocal manifest_writes
            if Path(path).name == ".manifest.json":
                manifest_writes += 1
                if manifest_writes == 2:
                    raise PermissionError("denied")
            return write(path, payload)
        with patch.dict(scope, {"_atomic_write_json": fail_finish}):
            with self.assertRaises(PermissionError):
                self.guard.cmd_snapshot_untracked(None, {"content": {}})
        self.assertEqual(self.guard._load_manifest()["pending_approvals"], {"example": "example"})
        self.guard.broadcast.assert_not_called()

    def test_bulk_approval_registers_unregistered_legacy_baseline(self):
        (self.site / "example.json").write_text("{}", encoding="utf-8")
        self.guard.cmd_snapshot_untracked(None, {"content": {}})
        manifest = self.guard._load_manifest()
        self.assertEqual(manifest["tracked_plugins"]["example"]["normalized"], "example")
        self.assertEqual(manifest["pending_approvals"], {})
        baseline = json.loads((self.site / "example.json").read_text(encoding="utf-8"))
        self.assertEqual(baseline["plugin.php"], hashlib.sha256(b"fixture").hexdigest())
        self.assertEqual(self.guard.broadcast.call_args.args[0]["approved_plugins"], ["example"])

    def test_bulk_approval_skips_colliding_legacy_names(self):
        shutil.rmtree(self.plugin)
        for name in ("example_1", "example_2"):
            (self.root / "plugins" / name).mkdir()
        old = self.site / "example.json"
        old.write_text("{}", encoding="utf-8")
        self.guard.cmd_snapshot_untracked(None, {"content": {}})
        self.assertEqual(self.guard._load_manifest()["tracked_plugins"], {})
        self.assertEqual(old.read_text(encoding="utf-8"), "{}")
        result = self.guard.broadcast.call_args.args[0]
        self.assertEqual(result["approved_plugins"], [])
        self.assertEqual(set(result["skipped_plugins"]), {"example_1", "example_2"})

    def test_restore_failure_after_move_keeps_pending_approval(self):
        shutil.rmtree(self.plugin)
        source = self.root / "quarantine" / "example_123"
        source.mkdir(parents=True)
        (source / "plugin.php").write_text("fixture", encoding="utf-8")
        write = scope["_atomic_write_json"]
        manifest_writes = 0
        def fail_finish(path, payload):
            nonlocal manifest_writes
            if Path(path).name == ".manifest.json":
                manifest_writes += 1
                if manifest_writes == 2:
                    raise PermissionError("denied")
            return write(path, payload)
        with patch.dict(scope, {"_atomic_write_json": fail_finish}):
            self.guard.cmd_restore_plugin(None, {"content": {"plugin": "example_123"}})
        self.assertTrue(self.plugin.exists())
        self.assertEqual(self.guard._load_manifest()["pending_approvals"], {"example": "example"})
        self.assertFalse(any("Auto-trusted" in str(args) for args, _ in self.guard.logs))

    def test_other_manifest_operation_waits_for_approval_transaction(self):
        started, proceed, second_done = threading.Event(), threading.Event(), threading.Event()
        snapshot = self.guard._snapshot_plugin
        def slow_snapshot(*args):
            started.set()
            if not proceed.wait(3):
                raise TimeoutError("test did not release snapshot")
            return snapshot(*args)
        def another_operation():
            self.guard._begin_approval("other", "other")
            second_done.set()
        with patch.object(self.guard, "_snapshot_plugin", side_effect=slow_snapshot):
            first = threading.Thread(target=self.approve)
            first.start()
            self.assertTrue(started.wait(2))
            second = threading.Thread(target=another_operation)
            second.start()
            self.assertFalse(second_done.wait(.1))
            proceed.set()
            first.join(3)
            second.join(3)
        self.assertFalse(first.is_alive())
        self.assertTrue(second_done.is_set())
        manifest = self.guard._load_manifest()
        self.assertIn("example", manifest["tracked_plugins"])
        self.assertEqual(manifest["pending_approvals"], {"other": "other"})

    @unittest.skipIf(fcntl is None, "POSIX file locks are unavailable")
    def test_approval_waits_for_another_process_holding_site_lock(self):
        ctx = multiprocessing.get_context("fork")
        ready, release = ctx.Event(), ctx.Event()
        process = ctx.Process(target=hold_approval_lock, args=(self.site, ready, release))
        done = threading.Event()
        thread = threading.Thread(target=lambda: (self.guard._begin_approval("example", "example"), done.set()))
        try:
            process.start()
            self.assertTrue(ready.wait(3))
            thread.start()
            self.assertFalse(done.wait(.1))
            release.set()
            thread.join(3)
            self.assertTrue(done.is_set())
            self.assertEqual(self.guard._load_manifest()["pending_approvals"], {"example": "example"})
        finally:
            release.set()
            if thread.is_alive():
                thread.join(3)
            process.join(3)
            if process.is_alive():
                process.terminate()
                process.join()

    def test_unreadable_plugin_walk_never_approves(self):
        def denied_walk(path, **kwargs):
            kwargs["onerror"](PermissionError("denied"))
            yield from ()
        with patch.object(os, "walk", side_effect=denied_walk):
            self.approve()
        self.assert_not_approved()
        self.assertEqual(self.guard._load_manifest()["pending_approvals"], {"example": "example"})


if __name__ == "__main__":
    unittest.main()
