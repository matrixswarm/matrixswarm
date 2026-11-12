import errno
import importlib.machinery
import importlib.util
import io
import os
import stat
import subprocess
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))

from core.python_core.class_lib.file_system.file_system_builder import FileSystemBuilder
from core.python_core.class_lib.logging.logger import Logger
from core.python_core.mixin.ghost_vault import build_encrypted_spawn_env, decrypt_vault, generate_agent_keypair
from core.python_core.reuse_cleanup import (cleanup_universe, cleanup_with_directive_and_key, prepare_reused_runtime,
    purge_runtime_paths, remove_directive_and_key, retire_active_signals)
from core.python_core.safe_paths import (_assert_admin_controlled, open_base, open_beneath,
    read_agent_source, runtime_directory, static_directory, trusted_agent_import_root,
    trusted_shared_agent_root, trusted_shared_core_root)
from core.python_core.swarm_session_root import SwarmSessionRoot


@unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux openat2")
class RuntimePathHardeningTests(unittest.TestCase):
    def test_builder_preserves_normal_nested_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "comm"
            FileSystemBuilder().process_selection(str(root), [
                {}, {"name": "config", "type": "d", "content": {"nested": {"a.json": {"key": "value"}}}},
                {"name": "status", "type": "f", "content": "ready", "atomic": True},
            ])
            self.assertEqual((root / "config/nested/a.json/key").read_text(), "value")
            self.assertEqual((root / "status").read_text(), "ready")

    def test_builder_rejects_escape_symlink_and_hardlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "comm"
            root.mkdir()
            outside = Path(temp) / "outside"
            outside.write_text("keep")
            (root / "link").symlink_to(outside)
            os.link(outside, root / "hardlink")
            builder = FileSystemBuilder()
            for name in ("../outside", str(outside), "link", "hardlink"):
                with self.subTest(name=name):
                    with self.assertRaises((ValueError, OSError)):
                        builder.process_item(str(root), {"name": name, "type": "f", "content": "bad"})
                    self.assertEqual(outside.read_text(), "keep")

    def test_anchor_rejects_nested_mount(self):
        fd = open_base("/")
        try:
            with self.assertRaises(OSError) as result:
                open_beneath(fd, "proc")
            self.assertEqual(result.exception.errno, errno.EXDEV)
        finally:
            os.close(fd)

    def test_unavailable_openat2_fails_before_creating_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "not-created"
            with patch("core.python_core.safe_paths._openat2", side_effect=RuntimeError("unavailable")):
                with self.assertRaisesRegex(RuntimeError, "unavailable"):
                    SwarmSessionRoot("u", str(root), "boot")
            self.assertFalse(root.exists())

    def test_latest_directory_is_never_destroyed(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp) / "universes/runtime/u/latest"
            parent.mkdir(parents=True)
            (parent / "user-data").write_text("keep")
            with self.assertRaises(ValueError):
                SwarmSessionRoot("u", temp, "boot1")
            self.assertEqual((parent / "user-data").read_text(), "keep")

    def test_latest_links_are_preserved_and_updated(self):
        with tempfile.TemporaryDirectory() as temp:
            SwarmSessionRoot("u", temp, "boot1")
            SwarmSessionRoot("u", temp, "boot2")
            for kind in ("runtime", "static"):
                latest = Path(temp) / "universes" / kind / "u/latest"
                self.assertTrue(latest.is_symlink())
                self.assertEqual(os.readlink(latest), "boot2")

    def test_held_runtime_handle_resists_ancestor_swap(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            real = base / "u/boot"
            channel = real / "comm/a/incoming"
            channel.mkdir(parents=True)
            (channel / "message").write_text("old")
            outside = base / "outside/boot/comm/a/incoming"
            outside.mkdir(parents=True)
            (outside / "message").write_text("outside")
            fd = open_base(real)
            try:
                (base / "u").rename(base / "original")
                (base / "u").symlink_to(base / "outside", target_is_directory=True)
                retire_active_signals(real, root_fd=fd)
            finally:
                os.close(fd)
            self.assertEqual((outside / "message").read_text(), "outside")
            self.assertFalse((base / "original/boot/comm/a/incoming/message").exists())
            self.assertEqual(len(list((base / "original/boot/retired-agent-signals").glob("*/a/incoming/message"))), 1)

    def test_clean_preflights_both_paths_before_removing_anything(self):
        with tempfile.TemporaryDirectory() as temp:
            boot = Path(temp) / "universes/runtime/u/boot"
            (boot / "comm/a").mkdir(parents=True)
            (boot / "comm/a/message").write_text("keep")
            outside = Path(temp) / "outside"
            outside.mkdir()
            (boot / "pod").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(OSError):
                purge_runtime_paths(temp, "u", "boot")
            self.assertEqual((boot / "comm/a/message").read_text(), "keep")
            self.assertTrue(outside.is_dir())

    def test_runtime_creation_refuses_symlinked_channel(self):
        with tempfile.TemporaryDirectory() as temp:
            SwarmSessionRoot("u", temp, "boot")
            outside = Path(temp) / "outside"
            outside.mkdir()
            channel = Path(temp) / "universes/runtime/u/boot/comm/a"
            channel.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(OSError):
                with runtime_directory(temp, "u", "boot", "comm", child="a", create_child=True):
                    pass
            self.assertEqual(list(outside.iterdir()), [])

    def test_installed_source_rejects_traversal_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "agents/python_core/test"
            source.mkdir(parents=True)
            agent = source / "test.py"
            agent.write_bytes(b"safe source")
            self.assertEqual(read_agent_source(temp, "python", "test", "py"), b"safe source")
            with self.assertRaises(ValueError):
                read_agent_source(temp, "python", "../test", "py")
            agent.unlink()
            outside = Path(temp) / "outside"
            outside.write_bytes(b"outside")
            agent.symlink_to(outside)
            with self.assertRaises(OSError):
                read_agent_source(temp, "python", "test", "py")

    def test_trusted_import_root_supports_sibling_import_and_rejects_unsafe_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            agent = Path(temp) / "agents/python_core/test"
            agent.mkdir(parents=True)
            for directory in (Path(temp) / "agents", Path(temp) / "agents/python_core", agent):
                directory.chmod(0o755)
            sibling = agent / "sibling.py"
            sibling.write_text("VALUE = 'verified sibling'\n")
            sibling.chmod(0o644)
            def fixture_admin_check(fd):
                # Production requires uid 0 and safe modes. The fixture uses
                # unprivileged temp dirs; retain the actual mode checks below
                # the trusted test root so no root privileges are required.
                path = Path(os.readlink(f"/proc/self/fd/{fd}"))
                if path == Path("/") or path == Path("/tmp"):
                    return
                if os.fstat(fd).st_mode & 0o022:
                    raise PermissionError("writable fixture")
            with patch("core.python_core.safe_paths._assert_admin_controlled", side_effect=fixture_admin_check):
                fd = trusted_agent_import_root(temp, "python", "test")
                try:
                    result = subprocess.run([sys.executable, "-B", "-c", "import sys;sys.path.insert(0,sys.argv[1]);import sibling;print(sibling.VALUE)", f"/proc/self/fd/{fd}"], pass_fds=(fd,), check=True, capture_output=True, text=True)
                    self.assertEqual(result.stdout.strip(), "verified sibling")
                finally:
                    os.close(fd)
                sibling.chmod(0o666)
                with self.assertRaises(PermissionError):
                    trusted_agent_import_root(temp, "python", "test")
                sibling.unlink()
                sibling.symlink_to(Path(temp) / "outside")
                with self.assertRaises(ValueError):
                    trusted_agent_import_root(temp, "python", "test")
                self.assertIsNone(trusted_agent_import_root(temp, "python", "missing"))

    def test_import_tree_enforces_admin_ownership_and_checks_shared_trees(self):
        with patch("core.python_core.safe_paths.os.fstat", return_value=SimpleNamespace(st_uid=1000, st_mode=0o755)):
            with self.assertRaises(PermissionError):
                _assert_admin_controlled(10)
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for directory in (base / "core", base / "agents", base / "agents/python_core", base / "agents/python_core/a"):
                directory.mkdir(exist_ok=True)
                directory.chmod(0o755)
            core_file = base / "core/module.py"
            core_file.write_text("x=1")
            core_file.chmod(0o644)
            agent_file = base / "agents/python_core/a/agent.py"
            agent_file.write_text("x=1")
            agent_file.chmod(0o644)
            def fixture_check(fd):
                path = Path(os.readlink(f"/proc/self/fd/{fd}"))
                if path in (Path("/"), Path("/tmp")):
                    return
                if os.fstat(fd).st_mode & 0o022:
                    raise PermissionError("writable fixture")
            with patch("core.python_core.safe_paths._assert_admin_controlled", side_effect=fixture_check):
                for method, args in ((trusted_shared_core_root, (temp,)),
                                     (trusted_shared_agent_root, (temp, "python"))):
                    fd = method(*args)
                    os.close(fd)
                core_file.chmod(0o666)
                with self.assertRaises(PermissionError):
                    trusted_shared_core_root(temp)
                agent_file.unlink()
                agent_file.symlink_to(core_file)
                with self.assertRaises(ValueError):
                    trusted_shared_agent_root(temp, "python")

    def test_anchored_vault_survives_pod_rename(self):
        with tempfile.TemporaryDirectory() as temp:
            pod = Path(temp) / "pod"
            pod.mkdir()
            fd = open_base(pod)
            child_fd = os.dup(fd)
            keys = generate_agent_keypair()
            payload = {"secure_keys": {"pub": keys["pub"], "priv": keys["priv"]},
                       "matrix_pub": keys["pub"], "example": "sentinel"}
            try:
                env = build_encrypted_spawn_env(payload, str(pod / "vault"), output_dir_fd=child_fd)
                pod.rename(Path(temp) / "original")
                pod.mkdir()
                (pod / "vault").write_text("outside")
                with patch.dict(os.environ, env, clear=True):
                    decrypted = decrypt_vault()
                self.assertEqual(decrypted["example"], "sentinel")
                with self.assertRaises(OSError):
                    os.fstat(child_fd)
                self.assertEqual((pod / "vault").read_text(), "outside")
                self.assertFalse((Path(temp) / "original/vault").exists())
            finally:
                os.close(fd)

    def test_pinned_vault_rejects_post_write_symlink_swap(self):
        with tempfile.TemporaryDirectory() as temp:
            pod = Path(temp) / "pod"
            pod.mkdir()
            outside = Path(temp) / "outside"
            outside.write_text("keep")
            fd = open_base(pod)
            keys = generate_agent_keypair()
            env = build_encrypted_spawn_env({"secure_keys": keys, "matrix_pub": keys["pub"]}, str(pod / "vault"), output_dir_fd=fd)
            (pod / "vault").unlink()
            (pod / "vault").symlink_to(outside)
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(RuntimeError):
                    decrypt_vault()
            self.assertEqual(outside.read_text(), "keep")
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_anchored_logger_follows_held_directory_after_rename(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "logs"
            path.mkdir()
            fd = open_base(path)
            logger = Logger(temp, "logs", "agent.log", max_bytes=1, directory_fd=fd)
            os.close(fd)
            try:
                path.rename(Path(temp) / "original")
                path.mkdir()
                logger.log("first", print_to_console=False)
                logger.log("second", print_to_console=False)
                self.assertIn("first", (Path(temp) / "original/agent.1.log").read_text())
                self.assertIn("second", (Path(temp) / "original/agent.log").read_text())
                self.assertFalse((path / "agent.log").exists())
            finally:
                logger.close()

    def test_anchored_logger_rejects_linked_log(self):
        with tempfile.TemporaryDirectory() as temp:
            logs = Path(temp) / "logs"
            logs.mkdir()
            outside = Path(temp) / "outside"
            outside.write_text("keep")
            fd = open_base(logs)
            logger = Logger(temp, directory_fd=fd)
            os.close(fd)
            try:
                for make_link in (lambda: (logs / "agent.log").symlink_to(outside),
                                  lambda: os.link(outside, logs / "agent.log")):
                    make_link()
                    logger.log("bad", print_to_console=False)
                    self.assertEqual(outside.read_text(), "keep")
                    (logs / "agent.log").unlink()
            finally:
                logger.close()

    def test_anchored_vault_refuses_existing_link(self):
        with tempfile.TemporaryDirectory() as temp:
            pod = Path(temp) / "pod"
            pod.mkdir()
            outside = Path(temp) / "outside"
            outside.write_text("keep")
            (pod / "vault").symlink_to(outside)
            fd = open_base(pod)
            keys = generate_agent_keypair()
            try:
                with self.assertRaises(RuntimeError):
                    build_encrypted_spawn_env({"secure_keys": keys}, str(pod / "vault"), output_dir_fd=fd)
                self.assertEqual(outside.read_text(), "keep")
            finally:
                os.close(fd)

    def test_preflight_rejects_unsafe_pod_before_retirement(self):
        with tempfile.TemporaryDirectory() as temp:
            SwarmSessionRoot("u", temp, "boot")
            runtime = Path(temp) / "universes/runtime/u/boot"
            removed = runtime / "comm/removed"
            removed.mkdir()
            (removed / "keep").write_text("safe")
            (runtime / "pod/unsafe").symlink_to(Path(temp), target_is_directory=True)
            with self.assertRaises(ValueError):
                prepare_reused_runtime(temp, "u", "boot", {"active"})
            self.assertEqual((removed / "keep").read_text(), "safe")
            self.assertFalse((runtime / "retired-agent-comm").exists())

    def test_reuse_rejects_static_ancestor_symlink_before_retirement(self):
        with tempfile.TemporaryDirectory() as temp:
            SwarmSessionRoot("u", temp, "boot")
            runtime = Path(temp) / "universes/runtime/u/boot"
            removed = runtime / "comm/removed"
            removed.mkdir()
            (removed / "keep").write_text("safe")
            static_boot = Path(temp) / "universes/static/u/boot"
            static_boot.rename(static_boot.with_name("original"))
            static_boot.symlink_to(Path(temp), target_is_directory=True)
            with self.assertRaises(OSError):
                prepare_reused_runtime(temp, "u", "boot", {"active"})
            self.assertEqual((removed / "keep").read_text(), "safe")
            self.assertFalse((runtime / "retired-agent-comm").exists())

    @unittest.skipIf(os.geteuid() == 0, "permission test requires an unprivileged user")
    def test_execute_only_ancestors_support_service_operations(self):
        with tempfile.TemporaryDirectory() as temp:
            SwarmSessionRoot("u", temp, "boot")
            roots = [Path(temp) / "universes", Path(temp) / "universes/runtime", Path(temp) / "universes/static"]
            for root in roots:
                root.chmod(0o111)
            try:
                with self.assertRaises(PermissionError):
                    os.open(roots[0], os.O_RDONLY | os.O_DIRECTORY)
                with runtime_directory(temp, "u", "boot", "comm", child="agent", create_child=True) as fd:
                    self.assertTrue(stat.S_ISDIR(os.fstat(fd).st_mode))
                with static_directory(temp, "u", "boot", "comm", child="agent", create_child=True) as fd:
                    self.assertTrue(stat.S_ISDIR(os.fstat(fd).st_mode))
                prepare_reused_runtime(temp, "u", "boot", {"agent"})
                SwarmSessionRoot("u", temp, "boot2")
            finally:
                for root in roots:
                    root.chmod(0o755)

    def test_cleanup_preflights_both_roots_before_deleting(self):
        with tempfile.TemporaryDirectory() as temp:
            for boot in ("20261110_010101", "20261111_010101"):
                SwarmSessionRoot("u", temp, boot)
            runtime = Path(temp) / "universes/runtime/u/20261110_010101/comm"
            (runtime / "sentinel").write_text("keep")
            static = Path(temp) / "universes/static/u/20261110_010101/comm"
            (static / "sentinel").write_text("keep")
            # Simulate the kernel rejecting a mount crossing in the static
            # tree. No runtime data should be removed before both preflights.
            from core.python_core import reuse_cleanup
            original = reuse_cleanup._tree_preflight
            def preflight(fd, depth=0):
                if os.readlink(f"/proc/self/fd/{fd}").endswith("/static/u/20261110_010101"):
                    raise OSError(errno.EXDEV, "mounted subtree")
                return original(fd, depth)
            with patch("core.python_core.reuse_cleanup._tree_preflight", side_effect=preflight):
                with self.assertRaises(OSError):
                    cleanup_universe(temp, "u", preserve_boot="20261111_010101")
            self.assertEqual((runtime / "sentinel").read_text(), "keep")
            self.assertEqual((static / "sentinel").read_text(), "keep")

    def test_prune_and_delete_preserve_expected_data(self):
        with tempfile.TemporaryDirectory() as temp:
            for boot in ("20261110_010101", "20261111_010101"):
                SwarmSessionRoot("u", temp, boot)
            for kind in ("runtime", "static"):
                universe = Path(temp) / "universes" / kind / "u"
                (universe / "persistent").mkdir()
                (universe / "persistent/keep").write_text("data")
                (universe / "20261110_010101/comm/proc-link").symlink_to("/proc", target_is_directory=True)
            removed = cleanup_universe(temp, "u", preserve_boot="20261111_010101")
            self.assertEqual(len(removed), 2)
            for kind in ("runtime", "static"):
                universe = Path(temp) / "universes" / kind / "u"
                self.assertFalse((universe / "20261110_010101").exists())
                self.assertTrue((universe / "20261111_010101").exists())
                self.assertEqual((universe / "persistent/keep").read_text(), "data")
                self.assertEqual(os.readlink(universe / "latest"), "20261111_010101")
            self.assertEqual(len(cleanup_universe(temp, "u", remove_all=True)), 2)
            self.assertTrue(Path("/proc/self").exists())

    def test_prune_preserves_resumed_old_boot_and_unknown_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            boots = ("20261109_010101", "20261110_010101", "20261111_010101")
            for boot in boots:
                SwarmSessionRoot("u", temp, boot)
            for kind in ("runtime", "static"):
                notes = Path(temp) / "universes" / kind / "u/notes"
                notes.mkdir()
                (notes / "keep").write_text("data")
            cleanup_universe(temp, "u", preserve_boot=boots[1])
            for kind in ("runtime", "static"):
                root = Path(temp) / "universes" / kind / "u"
                self.assertFalse((root / boots[0]).exists())
                self.assertTrue((root / boots[1]).exists())
                self.assertTrue((root / boots[2]).exists())
                self.assertEqual((root / "notes/keep").read_text(), "data")

    def test_prune_without_authoritative_boot_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            for boot in ("20261110_010101", "20261111_010101"):
                SwarmSessionRoot("u", temp, boot)
            with self.assertRaisesRegex(ValueError, "authoritative active boot"):
                cleanup_universe(temp, "u")
            for kind in ("runtime", "static"):
                self.assertTrue((Path(temp) / "universes" / kind / "u/20261110_010101").is_dir())

    def test_combined_cleanup_preflights_directives_and_all_trees(self):
        with tempfile.TemporaryDirectory() as temp:
            SwarmSessionRoot("u", temp, "20261111_010101")
            root = Path(temp) / "boot_directives"
            (root / "keys").mkdir(parents=True)
            directive, key = root / "u.enc.json", root / "keys/u.key"
            directive.write_text("directive")
            key.write_text("key")
            from core.python_core import reuse_cleanup
            original = reuse_cleanup._tree_preflight
            def preflight(fd, depth=0):
                if os.readlink(f"/proc/self/fd/{fd}").endswith("/static/u"):
                    raise OSError(errno.EXDEV, "mounted subtree")
                return original(fd, depth)
            with patch("core.python_core.reuse_cleanup._tree_preflight", side_effect=preflight):
                with self.assertRaises(OSError):
                    cleanup_with_directive_and_key(temp, "u")
            self.assertEqual(directive.read_text(), "directive")
            self.assertEqual(key.read_text(), "key")
            self.assertTrue((Path(temp) / "universes/runtime/u").is_dir())

    def test_exact_directive_cleanup_handles_missing_and_rejects_links(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            self.assertEqual(remove_directive_and_key(temp, "u"), [])
            root = base / "boot_directives"
            (root / "keys").mkdir(parents=True)
            directive = root / "u.enc.json"
            key = root / "keys/u.key"
            other = root / "other.enc.json"
            outside = base / "outside"
            directive.write_text("directive")
            other.write_text("other")
            outside.write_text("outside")
            key.symlink_to(outside)
            with self.assertRaises(ValueError):
                remove_directive_and_key(temp, "u")
            self.assertEqual(directive.read_text(), "directive")
            self.assertEqual(outside.read_text(), "outside")
            key.unlink()
            key.write_text("key")
            self.assertEqual(len(remove_directive_and_key(temp, "u")), 2)
            self.assertEqual(other.read_text(), "other")
            self.assertEqual(outside.read_text(), "outside")

    def test_exact_cleanup_keeps_key_parent_anchored_during_swap(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "boot_directives"
            keys = root / "keys"
            keys.mkdir(parents=True)
            (root / "u.enc.json").write_text("directive")
            (keys / "u.key").write_text("key")
            outside = base / "outside"
            outside.mkdir()
            (outside / "u.key").write_text("outside")
            real_unlink = os.unlink
            swapped = False
            def unlink(name, *, dir_fd=None):
                nonlocal swapped
                if name == "u.enc.json" and not swapped:
                    keys.rename(root / "original-keys")
                    keys.symlink_to(outside, target_is_directory=True)
                    swapped = True
                return real_unlink(name, dir_fd=dir_fd)
            with patch("core.python_core.reuse_cleanup.os.unlink", side_effect=unlink):
                self.assertEqual(len(remove_directive_and_key(temp, "u")), 2)
            self.assertTrue(swapped)
            self.assertEqual((outside / "u.key").read_text(), "outside")
            self.assertFalse((root / "original-keys/u.key").exists())

    def test_exact_cleanup_reports_partial_io_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "boot_directives"
            (root / "keys").mkdir(parents=True)
            directive, key = root / "u.enc.json", root / "keys/u.key"
            directive.write_text("directive")
            key.write_text("key")
            original_unlink = os.unlink
            def unlink(name, *, dir_fd=None):
                if name == "u.key":
                    raise OSError(errno.EIO, "simulated I/O error")
                return original_unlink(name, dir_fd=dir_fd)
            with patch("core.python_core.reuse_cleanup.os.unlink", side_effect=unlink):
                with self.assertRaises(OSError):
                    remove_directive_and_key(temp, "u")
            self.assertFalse(directive.exists())
            self.assertEqual(key.read_text(), "key")

    def test_cleanup_failure_warns_operator_of_possible_partial_deletion(self):
        loader = importlib.machinery.SourceFileLoader("matrixd_cleanup_warning_test", str(ROOT / "matrixos/scripts/matrixd"))
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(module, "get_all_swarm_agent_info", return_value=[]), \
             patch.object(module, "_assert_processes_visible"), \
             patch.object(module, "B2Bomber", return_value=SimpleNamespace(level_it=lambda _: True)), \
             patch.object(module, "cleanup_with_directive_and_key", side_effect=OSError("simulated failure")):
            output = io.StringIO()
            with redirect_stdout(output):
                result = module._kill_universe_fenced(temp, "u", cleanup=True, delete_directive_with_key=True)
            self.assertFalse(result)
            self.assertIn("Some files may already have been removed", output.getvalue())
            self.assertIn("directive, key, runtime and static", output.getvalue())


if __name__ == "__main__":
    unittest.main()
