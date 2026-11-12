"""Reuse retires only obsolete runtime channels and never static data."""
import os
import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
from core.python_core.core_spawner import CoreSpawner
from core.python_core.reuse_cleanup import retire_obsolete_runtime_comm, validate_directive_tree, validate_reuse_paths


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY"), "POSIX directory descriptors required")
class UniverseReuseCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.universe = "golden"
        self.boot = "20261111_120000"
        self.runtime = self.root / "universes" / "runtime" / self.universe / self.boot
        self.static = self.root / "universes" / "static" / self.universe / self.boot
        self.comm = self.runtime / "comm"
        (self.runtime / "pod").mkdir(parents=True)
        (self.static / "comm").mkdir(parents=True)
        self.comm.mkdir()
        self.args = SimpleNamespace(reboot_id=None, reboot_new=False, clean=False)

    def test_reuse_retires_only_obsolete_runtime_and_preserves_static(self):
        active = self.comm / "matrix" / "incoming"
        active.mkdir(parents=True)
        (active / "old-signal").write_text("transient", encoding="utf-8")
        old = self.comm / "removed-agent"
        (old / "queue").mkdir(parents=True)
        (old / "queue" / "valuable").write_text("retain", encoding="utf-8")
        (old / ".state").write_text("state", encoding="utf-8")
        old_static = self.static / "comm" / "removed-agent"
        (old_static / "logs").mkdir(parents=True)
        (old_static / "logs" / "agent.log").write_text("history", encoding="utf-8")
        (old_static / "quarantine").mkdir()
        (old_static / "quarantine" / "evidence").write_text("keep", encoding="utf-8")
        persistent = self.root / "universes" / "static" / self.universe / "persistent"
        persistent.mkdir()
        (persistent / "vault").write_text("keep", encoding="utf-8")

        CoreSpawner(self.universe, str(self.root), booting=True, args=self.args,
                    active_agent_ids={"matrix", "new-agent"})

        self.assertTrue((self.comm / "matrix").is_dir())
        self.assertFalse((active / "old-signal").exists())
        self.assertFalse(old.exists())
        retired = list((self.runtime / "retired-agent-comm").iterdir())
        self.assertEqual(len(retired), 1)
        self.assertEqual((retired[0] / "removed-agent" / "queue" / "valuable").read_text(), "retain")
        self.assertEqual((retired[0] / "removed-agent" / ".state").read_text(), "state")
        self.assertEqual((old_static / "logs" / "agent.log").read_text(), "history")
        self.assertEqual((old_static / "quarantine" / "evidence").read_text(), "keep")
        self.assertEqual((persistent / "vault").read_text(), "keep")

    def test_no_obsolete_agents_creates_no_archive(self):
        (self.comm / "matrix").mkdir()
        self.assertIsNone(retire_obsolete_runtime_comm(self.runtime, {"matrix"}))
        self.assertFalse((self.runtime / "retired-agent-comm").exists())

    def test_fresh_universe_boots_with_or_without_reboot_new(self):
        for reboot_new in (False, True):
            with self.subTest(reboot_new=reboot_new), tempfile.TemporaryDirectory() as base:
                args = SimpleNamespace(reboot_id=None, reboot_new=reboot_new, clean=False)
                spawner = CoreSpawner(self.universe, base, booting=True, args=args,
                                      active_agent_ids={"matrix"})
                self.assertTrue(Path(spawner.pm.session.runtime_root).is_dir())

    def test_invalid_universe_exits_before_creating_runtime_directories(self):
        script = """import importlib.machinery, importlib.util, sys
from types import SimpleNamespace
loader = importlib.machinery.SourceFileLoader('matrixd_fixture', sys.argv[1])
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
module.boot_universe('../escape', SimpleNamespace(directive_stdin=True), base=sys.argv[2])
"""
        result = subprocess.run([sys.executable, "-B", "-c", script,
                                 str(ROOT / "matrixos/scripts/matrixd"), str(self.root)],
                                env={**os.environ, "PYTHONPATH": str(ROOT / "matrixos")},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse((self.root / "universes" / "runtime" / "escape").exists())

    def test_replacement_agent_after_shutdown_aborts_before_spawner(self):
        loader = importlib.machinery.SourceFileLoader("matrixd_reuse_test", str(ROOT / "matrixos/scripts/matrixd"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        from core.python_core.lifecycle_fence import LifecycleFence
        lifecycle = self.root / "universes/lifecycle/golden"
        lifecycle.mkdir(parents=True)
        lifecycle.parent.parent.chmod(0o755)
        lifecycle.parent.chmod(0o755)
        lifecycle.chmod(0o750)
        lock = lifecycle / "lock"
        lock.write_text('{"version":1,"state":"ACTIVE","generation":"' + "a" * 32 + '","boot_id":"20261111_120000"}')
        lock.chmod(0o660)
        args = SimpleNamespace(directive_stdin=True)
        with patch.object(module, "LifecycleFence", side_effect=lambda base, universe: LifecycleFence(base, universe, _owner_uid=os.getuid())), \
             patch.object(module, "trusted_shared_core_root", side_effect=lambda base: os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)), \
             patch.object(module, "trusted_shared_agent_root", side_effect=lambda base, lang: os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)), \
             patch.object(module, "_assert_processes_visible"), \
             patch.object(module, "enforce_single_matrix_instance"), \
             patch.object(module, "read_boot_envelope", return_value=({}, "key")), \
             patch.object(module, "decrypt_directive_bundle", return_value={"universal_id": "matrix", "name": "matrix"}), \
             patch.object(module, "get_all_swarm_agent_info", side_effect=[[], [], [{"pid": 123}]]), \
             patch.object(module, "B2Bomber") as bomber, \
             patch.object(module, "CoreSpawner") as spawner:
            bomber.return_value.level_it.return_value = True
            with self.assertRaisesRegex(RuntimeError, "appeared after shutdown"):
                module.boot_universe(self.universe, args, base=str(self.root))
            spawner.assert_not_called()

    def test_duplicate_boot_does_not_disable_active_generation(self):
        loader = importlib.machinery.SourceFileLoader("matrixd_duplicate_test", str(ROOT / "matrixos/scripts/matrixd"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        from core.python_core.lifecycle_fence import LifecycleFence
        lifecycle = self.root / "universes/lifecycle/golden"
        lifecycle.mkdir(parents=True)
        lifecycle.parent.parent.chmod(0o755)
        lifecycle.parent.chmod(0o755)
        lifecycle.chmod(0o750)
        lock = lifecycle / "lock"
        lock.write_text('{"version":1,"state":"ACTIVE","generation":"' + "a" * 32 + '","boot_id":"20261111_120000"}')
        lock.chmod(0o660)
        with patch.object(module, "LifecycleFence", side_effect=lambda base, universe: LifecycleFence(base, universe, _owner_uid=os.getuid())), \
             patch.object(module, "trusted_shared_core_root", side_effect=lambda base: os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)), \
             patch.object(module, "trusted_shared_agent_root", side_effect=lambda base, lang: os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)), \
             patch.object(module, "_assert_processes_visible"), \
             patch.object(module, "enforce_single_matrix_instance", side_effect=SystemExit(1)), \
             patch.object(module, "read_boot_envelope", return_value=({}, "key")), \
             patch.object(module, "decrypt_directive_bundle", return_value={"universal_id": "matrix", "name": "matrix"}), \
             patch.object(module, "get_all_swarm_agent_info", return_value=[]):
            with self.assertRaises(SystemExit):
                module.boot_universe(self.universe, SimpleNamespace(directive_stdin=True), base=str(self.root))
        with LifecycleFence(self.root, self.universe, _owner_uid=os.getuid()).shared("a" * 32):
            pass

    def test_invalid_ids_fail_before_mutation(self):
        (self.comm / "removed").mkdir()
        for ids in ([], ["matrix", "matrix"], ["../escape"], ["a/b"], ["a\\b"], ["."], ["a.b"], ["a b"], ["é"], [None]):
            with self.subTest(ids=ids):
                with self.assertRaises(ValueError):
                    retire_obsolete_runtime_comm(self.runtime, ids)
                self.assertTrue((self.comm / "removed").exists())
                self.assertFalse((self.runtime / "retired-agent-comm").exists())

    def test_raw_directive_validation_rejects_silently_discarded_nodes(self):
        for child in ({"name": "missing-id"}, None, {"universal_id": "../outside"},
                      {"universal_id": "matrix"}):
            with self.subTest(child=child), self.assertRaises(ValueError):
                validate_directive_tree({"universal_id": "matrix", "children": [child]})
        self.assertEqual(validate_directive_tree({"agent_tree": {"universal_id": "matrix",
            "children": [{"enabled": False, "children": [None]}, {"universal_id": "active"}]}}),
            {"matrix", "active"})

    def test_active_control_files_are_recoverable_in_separate_batch(self):
        agent = self.comm / "matrix"
        for channel in ("incoming", "hello.moto", "spawn", "directive"):
            (agent / channel).mkdir(parents=True)
            (agent / channel / "packet").write_text(channel)
            (agent / channel / "nested").mkdir()
        CoreSpawner(self.universe, str(self.root), booting=True, args=self.args,
                    active_agent_ids={"matrix"})
        archive = next((self.runtime / "retired-agent-signals").iterdir())
        for channel in ("incoming", "hello.moto", "spawn", "directive"):
            self.assertFalse((agent / channel / "packet").exists())
            self.assertTrue((agent / channel / "nested").is_dir())
            self.assertEqual((archive / "matrix" / channel / "packet").read_text(), channel)

    def test_signal_retirement_failure_aborts_before_pod_cleanup(self):
        agent = self.comm / "matrix" / "incoming"
        agent.mkdir(parents=True)
        (agent / "packet").write_text("retain")
        pod = self.runtime / "pod" / "old-pod"
        pod.mkdir()
        with patch("core.python_core.reuse_cleanup.os.rename", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                CoreSpawner(self.universe, str(self.root), booting=True, args=self.args,
                            active_agent_ids={"matrix"})
        self.assertEqual((agent / "packet").read_text(), "retain")
        self.assertTrue(pod.is_dir())

    def test_pod_symlink_aborts_before_channel_retirement(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.runtime / "pod" / "bad").symlink_to(outside, target_is_directory=True)
        (self.comm / "removed").mkdir()
        (self.comm / "matrix" / "incoming").mkdir(parents=True)
        signal = self.comm / "matrix" / "incoming" / "packet"
        signal.write_text("keep")
        with self.assertRaises(ValueError):
            CoreSpawner(self.universe, str(self.root), booting=True, args=self.args,
                        active_agent_ids={"matrix"})
        self.assertTrue((self.comm / "removed").exists())
        self.assertTrue(signal.exists())
        self.assertFalse((self.runtime / "retired-agent-comm").exists())

    def test_failed_pod_deletion_leaves_retired_channels_recoverable(self):
        (self.comm / "removed").mkdir()
        (self.comm / "removed" / "state").write_text("keep")
        (self.comm / "matrix" / "incoming").mkdir(parents=True)
        (self.comm / "matrix" / "incoming" / "packet").write_text("retain")
        (self.runtime / "pod" / "old-pod").mkdir()
        with patch("core.python_core.reuse_cleanup._remove_contents", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                CoreSpawner(self.universe, str(self.root), booting=True, args=self.args,
                            active_agent_ids={"matrix"})
        comm_archive = next((self.runtime / "retired-agent-comm").iterdir())
        signal_archive = next((self.runtime / "retired-agent-signals").iterdir())
        self.assertEqual((comm_archive / "removed" / "state").read_text(), "keep")
        self.assertEqual((signal_archive / "matrix" / "incoming" / "packet").read_text(), "retain")

    def test_signal_retirement_under_low_descriptor_limit(self):
        for index in range(30):
            for channel in ("incoming", "hello.moto", "spawn", "directive"):
                directory = self.comm / f"agent-{index}" / channel
                directory.mkdir(parents=True)
                (directory / "packet").write_text(f"{index}-{channel}")
        script = """import resource, sys
from core.python_core.reuse_cleanup import retire_active_signals
resource.setrlimit(resource.RLIMIT_NOFILE, (40, 40))
print(retire_active_signals(sys.argv[1]))
"""
        result = subprocess.run([sys.executable, "-B", "-c", script, str(self.runtime)],
                                env={**os.environ, "PYTHONPATH": str(ROOT / "matrixos")},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = Path(result.stdout.strip())
        for index in range(30):
            for channel in ("incoming", "hello.moto", "spawn", "directive"):
                self.assertEqual((archive / f"agent-{index}" / channel / "packet").read_text(),
                                 f"{index}-{channel}")
                self.assertFalse((self.comm / f"agent-{index}" / channel / "packet").exists())

    def test_symlink_channel_fails_without_touching_external_data(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "fixture").write_text("keep", encoding="utf-8")
        (self.comm / "matrix").mkdir()
        (self.comm / "linked").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            retire_obsolete_runtime_comm(self.runtime, {"matrix"})
        self.assertEqual((outside / "fixture").read_text(), "keep")
        self.assertFalse((self.runtime / "retired-agent-comm").exists())

    def test_active_control_symlink_stops_before_retirement(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "fixture").write_text("keep", encoding="utf-8")
        (self.comm / "matrix").mkdir()
        (self.comm / "matrix" / "incoming").symlink_to(outside, target_is_directory=True)
        (self.comm / "removed").mkdir()
        with self.assertRaises(OSError):
            retire_obsolete_runtime_comm(self.runtime, {"matrix"})
        self.assertTrue((self.comm / "removed").exists())
        self.assertTrue((outside / "fixture").exists())

    def test_retirement_directory_symlink_refuses_even_if_no_obsolete(self):
        (self.comm / "matrix").mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (self.runtime / "retired-agent-comm").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            retire_obsolete_runtime_comm(self.runtime, {"matrix"})
        self.assertEqual(list(outside.iterdir()), [])

    def test_failed_move_aborts_reuse_before_runtime_cleanup(self):
        (self.comm / "matrix" / "incoming").mkdir(parents=True)
        cookie = self.comm / "matrix" / "incoming" / "cookie"
        cookie.write_text("keep", encoding="utf-8")
        (self.comm / "removed").mkdir()
        with patch("core.python_core.reuse_cleanup.os.rename", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                CoreSpawner(self.universe, str(self.root), booting=True, args=self.args,
                            active_agent_ids={"matrix"})
        self.assertTrue((self.comm / "removed").exists())
        self.assertTrue(cookie.exists())

    def test_partial_move_failure_keeps_every_folder_recoverable(self):
        (self.comm / "matrix" / "incoming").mkdir(parents=True)
        cookie = self.comm / "matrix" / "incoming" / "cookie"
        cookie.write_text("keep")
        for name in ("removed-one", "removed-two"):
            (self.comm / name).mkdir()
            (self.comm / name / "state").write_text(name)
        original_rename = os.rename
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(args)
            if len(calls) == 2:
                raise PermissionError("denied")
            return original_rename(*args, **kwargs)

        with patch("core.python_core.reuse_cleanup.os.rename", side_effect=fail_second):
            with self.assertRaises(PermissionError):
                CoreSpawner(self.universe, str(self.root), booting=True, args=self.args,
                            active_agent_ids={"matrix"})
        archive = next((self.runtime / "retired-agent-comm").iterdir())
        for name in ("removed-one", "removed-two"):
            locations = [path for path in (self.comm / name, archive / name) if path.exists()]
            self.assertEqual(len(locations), 1)
            self.assertEqual((locations[0] / "state").read_text(), name)
        self.assertTrue(cookie.exists())

    def test_symlinked_boot_root_is_rejected(self):
        other = self.root / "outside"
        other.mkdir()
        (self.runtime.parent / "20261112_000000").symlink_to(other, target_is_directory=True)
        with self.assertRaises(ValueError):
            validate_reuse_paths(self.root, self.universe, "20261112_000000")

    def test_explicit_resume_also_retires_obsolete(self):
        (self.comm / "matrix").mkdir()
        (self.comm / "removed").mkdir()
        self.args.reboot_id = self.boot
        CoreSpawner(self.universe, str(self.root), booting=True, args=self.args,
                    active_agent_ids={"matrix"})
        self.assertFalse((self.comm / "removed").exists())
        self.assertEqual(len(list((self.runtime / "retired-agent-comm").iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
