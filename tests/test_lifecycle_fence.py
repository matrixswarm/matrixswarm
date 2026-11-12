import json
import importlib.machinery
import importlib.util
import subprocess
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
from core.python_core.lifecycle_fence import LifecycleError, LifecycleFence


class FenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.directory = self.base / "universes/lifecycle/golden"
        self.directory.mkdir(parents=True)
        (self.base / "universes").chmod(0o755)
        self.directory.parent.chmod(0o755)
        self.directory.chmod(0o750)
        self.lock = self.directory / "lock"
        self.lock.write_text(json.dumps({"version": 1, "state": "STOPPED", "generation": None, "boot_id": None}))
        self.lock.chmod(0o660)
        self.generation = "a" * 32

    def fence(self):
        return LifecycleFence(self.base, "golden", _owner_uid=os.getuid())

    def test_generation_rejects_stale_and_inactive(self):
        with self.fence().exclusive() as f:
            f.write_state("ACTIVE", self.generation, "20261112_120000")
        with self.fence().shared(self.generation) as f:
            self.assertEqual(f.read_state()["boot_id"], "20261112_120000")
        with self.assertRaises(LifecycleError), self.fence().shared("b" * 32):
            pass
        with self.fence().exclusive() as f:
            f.write_state("STOPPING", self.generation, "20261112_120000")
        with self.assertRaises(LifecycleError), self.fence().shared(self.generation):
            pass

    def test_locked_spawn_fails_without_waiting(self):
        with self.fence().exclusive() as f:
            f.write_state("ACTIVE", self.generation, "20261112_120000")
            with self.assertRaises(LifecycleError), self.fence().shared(self.generation):
                pass

    def test_traversal_does_not_require_directory_read_permission(self):
        (self.base / "universes").chmod(0o111)
        self.directory.parent.chmod(0o111)
        self.addCleanup(lambda: (self.base / "universes").chmod(0o755))
        self.addCleanup(lambda: self.directory.parent.chmod(0o755))
        with self.fence().exclusive() as f:
            self.assertEqual(f.read_state()["state"], "STOPPED")

    def test_separate_process_cannot_spawn_during_exclusive_operation(self):
        code = ("import os,sys\n"
                "from core.python_core.lifecycle_fence import LifecycleFence, LifecycleError\n"
                "try:\n"
                " with LifecycleFence(sys.argv[1], 'golden', _owner_uid=os.getuid()).shared(sys.argv[2]): pass\n"
                "except LifecycleError: sys.exit(23)\n")
        with self.fence().exclusive() as f:
            f.write_state("ACTIVE", self.generation, "20261112_120000")
            env = {**os.environ, "PYTHONPATH": str(ROOT / "matrixos")}
            result = subprocess.run([sys.executable, "-B", "-c", code, str(self.base), self.generation],
                                    env=env, timeout=5)
            self.assertEqual(result.returncode, 23)

    def test_agent_spawn_checks_fence_before_constructing_spawner(self):
        from core.python_core.boot_agent import BootAgent
        import core.python_core.boot_agent as module
        with self.fence().exclusive() as f:
            f.write_state("ACTIVE", self.generation, "20261112_120000")
        calls = []
        agent = SimpleNamespace(path_resolution={"install_path": str(self.base), "reboot_uuid": "20261112_120000"},
                                command_line_args={"universe": "golden"},
                                _spawn_agent_direct_fenced=lambda *args: calls.append(args),
                                log=lambda *args, **kwargs: None)
        with patch.object(module, "LifecycleFence", side_effect=lambda base, universe: self.fence()), \
             patch.dict(os.environ, {module.GENERATION_ENV: self.generation}):
            with self.fence().exclusive():
                BootAgent.spawn_agent_direct(agent, "golden", "matrix", "child", "child", {})
            self.assertEqual(calls, [])
            BootAgent.spawn_agent_direct(agent, "golden", "matrix", "child", "child", {})
            self.assertEqual(len(calls), 1)
            BootAgent.spawn_agent_direct(agent, "other", "matrix", "child", "child", {})
            self.assertEqual(len(calls), 1)
        with patch.object(module, "LifecycleFence", side_effect=lambda base, universe: self.fence()), \
             patch.dict(os.environ, {module.GENERATION_ENV: "b" * 32}):
            BootAgent.spawn_agent_direct(agent, "golden", "matrix", "child2", "child", {})
            self.assertEqual(len(calls), 1)

    def test_corrupt_state_and_untrusted_files_fail_closed(self):
        self.lock.write_text("")
        with self.fence().exclusive() as f:
            with self.assertRaises(LifecycleError):
                f.read_state()
        self.lock.unlink()
        self.lock.symlink_to("/dev/null")
        with self.assertRaises(OSError), self.fence().exclusive():
            pass

    def test_ancestor_symlink_is_rejected(self):
        real = self.base / "universes/lifecycle"
        moved = self.base / "moved"
        real.rename(moved)
        real.symlink_to(moved)
        with self.assertRaises(OSError), self.fence().exclusive():
            pass

    def test_explicit_recovery_preserves_inode_and_refuses_live_agent(self):
        loader = importlib.machinery.SourceFileLoader("matrixd_recovery_test", str(ROOT / "matrixos/scripts/matrixd"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        self.lock.write_text('{"partial"')
        inode = self.lock.stat().st_ino
        process = SimpleNamespace(info={"pid": 42, "cmdline": ["python", "--job", "golden:agent"], "status": "running", "ppid": 1})
        with patch.object(module, "LifecycleFence", side_effect=lambda base, universe: self.fence()), \
             patch.object(module.os, "geteuid", return_value=0), \
             patch.object(module.psutil, "process_iter", return_value=[process]):
            with self.assertRaisesRegex(RuntimeError, "live or pending"):
                module.recover_lifecycle(self.base, "golden", confirmed=True)
        self.assertEqual(self.lock.read_text(), '{"partial"')
        with patch.object(module, "LifecycleFence", side_effect=lambda base, universe: self.fence()), \
             patch.object(module.os, "geteuid", return_value=0), \
             patch.object(module.psutil, "process_iter", return_value=[]):
            module.recover_lifecycle(self.base, "golden", confirmed=True)
        self.assertEqual(self.lock.stat().st_ino, inode)
        with self.fence().exclusive() as f:
            self.assertEqual(f.read_state()["state"], "STOPPED")

    def test_process_visibility_fails_closed_for_hidden_and_unrecognized_jobs(self):
        loader = importlib.machinery.SourceFileLoader("matrixd_visibility_test", str(ROOT / "matrixos/scripts/matrixd"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        hidden = "1 2 0:5 / /proc rw - proc proc rw,hidepid=2\n"
        with patch.object(module.Path, "read_text", return_value=hidden):
            with self.assertRaisesRegex(RuntimeError, "hides processes"):
                module._assert_procfs_visibility()
        visible = "1 2 0:5 / /proc rw - proc proc rw\n"
        unknown = SimpleNamespace(info={"pid": 55, "cmdline": None, "status": "running", "ppid": 1})
        job = SimpleNamespace(info={"pid": 56, "cmdline": ["python", "--job", "golden:child"], "status": "running", "ppid": 1})
        with patch.object(module.Path, "read_text", return_value=visible), \
             patch.object(module.psutil, "process_iter", return_value=[unknown]):
            with self.assertRaisesRegex(RuntimeError, "Cannot inspect"):
                module._assert_processes_visible("golden", [])
        with patch.object(module.Path, "read_text", return_value=visible), \
             patch.object(module.psutil, "process_iter", return_value=[job]):
            with self.assertRaisesRegex(RuntimeError, "Unrecognized"):
                module._assert_processes_visible("golden", [])
            module._assert_processes_visible("golden", [{"pid": 56}])

    def test_normal_stop_retains_boot_for_later_prune(self):
        loader = importlib.machinery.SourceFileLoader("matrixd_preserve_test", str(ROOT / "matrixos/scripts/matrixd"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        boot_id = "20261112_120000"
        with self.fence().exclusive() as f:
            f.write_state("ACTIVE", self.generation, boot_id)
        with patch.object(module, "LifecycleFence", side_effect=lambda base, universe: self.fence()), \
             patch.object(module, "get_all_swarm_agent_info", return_value=[]), \
             patch.object(module, "_assert_processes_visible"), \
             patch.object(module, "_kill_universe_fenced", return_value=True) as stop:
            self.assertTrue(module.kill_universe(self.base, "golden"))
            with self.fence().exclusive() as f:
                self.assertEqual(f.read_state()["boot_id"], boot_id)
            self.assertTrue(module.kill_universe(self.base, "golden", cleanup=True))
            self.assertEqual(stop.call_args.kwargs["preserve_boot"], boot_id)


if __name__ == "__main__":
    unittest.main()
