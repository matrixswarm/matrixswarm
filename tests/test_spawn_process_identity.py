"""Boot metadata records the actual spawned process identity when available."""
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import sys
import tempfile
import threading
import subprocess
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
from core.python_core.core_spawner import CoreSpawner, _publish_boot_record


class SpawnProcessIdentityTests(unittest.TestCase):
    def test_clean_boot_creates_usable_comm_and_pod_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            spawner = CoreSpawner("clean-test", temp, booting=True,
                args=SimpleNamespace(reboot_id=None, reboot_new=True, clean=True),
                active_agent_ids={"matrix"})
            comm = Path(spawner.ensure_comm_channel("matrix", []))
            self.assertTrue((comm / "incoming").is_dir())
            _, pod = spawner.create_runtime()
            self.assertTrue(Path(pod).is_dir())

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        gate = Path(self.tmp.name) / "core/python_core/gated_launcher.py"
        gate.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "matrixos/core/python_core/gated_launcher.py", gate)
        shutil.copyfile(ROOT / "matrixos/core/python_core/fd_launcher.py", gate.with_name("fd_launcher.py"))
        shutil.copyfile(ROOT / "matrixos/core/python_core/protected_launcher.py", gate.with_name("protected_launcher.py"))
        self.spawner = CoreSpawner("golden", self.tmp.name, python_site=self.tmp.name,
            detected_python=sys.executable, booting=True,
            args=SimpleNamespace(reboot_id=None, reboot_new=True, clean=False),
            active_agent_ids={"matrix"})
        self.spawner._keychain = {key: "test" for key in
            ("pub", "priv", "swarm_key", "private_key", "matrix_pub", "matrix_priv", "security_box")}
        self.spawner._keychain["encryption_enabled"] = False
        self.spawner.ensure_comm_channel("test-agent", [])
        for name in ("trusted_shared_core_root", "trusted_shared_agent_root"):
            mock = patch("core.python_core.core_spawner." + name,
                         side_effect=lambda *args: os.open(self.tmp.name, os.O_RDONLY | os.O_DIRECTORY))
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch("core.python_core.core_spawner.trusted_agent_import_root", return_value=None)
        mock.start()
        self.addCleanup(mock.stop)

    def spawn(self):
        source = base64.b64encode(b"import time\ntime.sleep(60)\n").decode()
        with patch("core.python_core.core_spawner.build_encrypted_spawn_env", return_value=dict(os.environ)):
            pid, _ = self.spawner.spawn_agent("golden", "matrix", "test-agent", "test-agent", "pod1",
                                              {"src_embed": source})
        self.addCleanup(self.stop_child, pid)
        path = Path(self.spawner.pm.session.runtime_pod_path) / "pod1" / "boot.json"
        return pid, json.loads(path.read_text())

    @staticmethod
    def stop_child(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            os.waitpid(pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass

    def test_boot_record_matches_actual_process_start_time(self):
        pid, record = self.spawn()
        self.assertEqual(record["pid"], pid)
        self.assertEqual(record["process_started_at"], psutil.Process(pid).create_time())
        self.assertIsInstance(record["process_started_at"], float)
        self.assertEqual(record["source_sha256"], hashlib.sha256(b"import time\ntime.sleep(60)\n").hexdigest())

    def test_unavailable_start_time_is_not_invented(self):
        with patch("core.python_core.core_spawner.psutil.Process", side_effect=psutil.AccessDenied()):
            pid, record = self.spawn()
        self.assertEqual(record["pid"], pid)
        self.assertNotIn("process_started_at", record)

    def test_spawn_audit_is_anchored_in_static_tree_and_rejects_link(self):
        self.spawn()
        audit = Path(self.spawner.pm.session.static_root) / "spawn.log"
        self.assertIn("test-agent", audit.read_text())
        self.assertFalse((Path(self.tmp.name) / "spawn.log").exists())
        outside = Path(self.tmp.name) / "outside"
        outside.write_text("keep")
        audit.unlink()
        audit.symlink_to(outside)
        source = base64.b64encode(b"pass\n").decode()
        with self.assertRaises(RuntimeError):
            self.spawner.spawn_agent("golden", "matrix", "test-agent", "test-agent", "pod2", {"src_embed": source})
        self.assertEqual(outside.read_text(), "keep")

    def test_boot_publish_hides_partial_write_and_preserves_permissions(self):
        path = Path(self.tmp.name) / "boot.json"
        path.write_text('{"pid": 1}')
        path.chmod(0o600)
        started, finish = threading.Event(), threading.Event()
        errors = []

        def delayed_dump(record, file, **kwargs):
            file.write('{"pid": ')
            file.flush()
            started.set()
            if not finish.wait(5):
                raise TimeoutError("test stalled")
            file.write('2}')

        def publish():
            try:
                _publish_boot_record(path, {"pid": 2})
            except Exception as error:
                errors.append(error)

        with patch("core.python_core.core_spawner.json.dump", side_effect=delayed_dump):
            worker = threading.Thread(target=publish)
            worker.start()
            try:
                self.assertTrue(started.wait(5))
                self.assertEqual(json.loads(path.read_text()), {"pid": 1})
            finally:
                finish.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(json.loads(path.read_text()), {"pid": 2})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(path.parent.glob(".boot.json.*.tmp")), [])

    def test_failed_boot_publish_preserves_previous_record(self):
        path = Path(self.tmp.name) / "boot.json"
        path.write_text('{"pid": 1}')

        def fail_dump(record, file, **kwargs):
            file.write('{"pid":')
            raise OSError("disk full")

        with patch("core.python_core.core_spawner.json.dump", side_effect=fail_dump):
            with self.assertRaises(OSError):
                _publish_boot_record(path, {"pid": 2})
        self.assertEqual(json.loads(path.read_text()), {"pid": 1})
        self.assertEqual(list(path.parent.glob(".boot.json.*.tmp")), [])

    def test_new_boot_record_uses_normal_creation_mode(self):
        path = Path(self.tmp.name) / "boot.json"
        control = Path(self.tmp.name) / "control"
        control.write_text("control")
        _publish_boot_record(path, {"pid": 2})
        self.assertEqual(path.stat().st_mode & 0o777, control.stat().st_mode & 0o777)

    def test_launch_gate_runs_only_after_parent_releases_it(self):
        marker = Path(self.tmp.name) / "ran"
        gate = Path(self.tmp.name) / "core/python_core/gated_launcher.py"
        command = [sys.executable, "-c", "from pathlib import Path; Path(%r).write_text('ok')" % str(marker)]
        env = {**os.environ, "MATRIX_GATED_COMMAND": json.dumps(command)}
        process = subprocess.Popen([sys.executable, str(gate)], stdin=subprocess.PIPE, env=env)
        self.assertFalse(marker.exists())
        process.stdin.close()
        self.assertNotEqual(process.wait(timeout=5), 0)
        self.assertFalse(marker.exists())
        process = subprocess.Popen([sys.executable, str(gate)], stdin=subprocess.PIPE, env=env)
        process.stdin.write(b"1")
        process.stdin.close()
        self.assertEqual(process.wait(timeout=5), 0)
        self.assertEqual(marker.read_text(), "ok")

    def test_readiness_requires_explicit_acknowledgement(self):
        for ack in (False, True):
            with self.subTest(ack=ack):
                code = ("import os\nfd=int(os.environ['MATRIX_BOOT_READY_FD'])\n" +
                        ("os.write(fd,b'1')\n" if ack else "") + "os.close(fd)\n")
                with patch("core.python_core.core_spawner.build_encrypted_spawn_env", return_value=dict(os.environ)):
                    pid, _ = self.spawner.spawn_agent("golden", "matrix", "test-agent", "test-agent",
                        "ready-yes" if ack else "ready-no", {"src_embed": base64.b64encode(code.encode()).decode()},
                        defer_gate=True, require_ready=True)
                self.addCleanup(self.stop_child, pid)
                self.spawner.release_pending_gate()
                if ack:
                    self.spawner.wait_until_ready(timeout=5)
                else:
                    with self.assertRaisesRegex(RuntimeError, "did not report"):
                        self.spawner.wait_until_ready(timeout=5)

    def test_process_discovery_finds_pending_gate_and_fd_launcher(self):
        from core.python_core.swarm_processes import get_all_swarm_agent_info
        source = base64.b64encode(b"import time\ntime.sleep(30)\n").decode()
        pod = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        with patch("core.python_core.core_spawner.build_encrypted_spawn_env", return_value=dict(os.environ)):
            pid, _ = self.spawner.spawn_agent("golden", "matrix", "test-agent", "test-agent", pod,
                                              {"src_embed": source}, defer_gate=True)
        self.addCleanup(self.stop_child, pid)
        self.assertIn(pid, [entry["pid"] for entry in get_all_swarm_agent_info("golden", base=self.tmp.name)])
        self.spawner.release_pending_gate()
        for _ in range(100):
            try:
                if "fd_launcher.py" in " ".join(psutil.Process(pid).cmdline()):
                    break
            except psutil.NoSuchProcess:
                break
            time.sleep(0.02)
        self.assertIn(pid, [entry["pid"] for entry in get_all_swarm_agent_info("golden", base=self.tmp.name)])

    def test_agent_imports_sibling_from_pinned_source_directory(self):
        import_dir = Path(self.tmp.name) / "trusted-agent"
        import_dir.mkdir()
        (import_dir / "sibling.py").write_text("VALUE = 'trusted'\n")
        marker = Path(self.tmp.name) / "sibling-result"
        source = ("from pathlib import Path\nimport sibling\n"
                  "Path(%r).write_text(sibling.VALUE)\n") % str(marker)
        with patch("core.python_core.core_spawner.trusted_agent_import_root",
                   side_effect=lambda *args: os.open(import_dir, os.O_RDONLY | os.O_DIRECTORY)), \
             patch("core.python_core.core_spawner.build_encrypted_spawn_env", return_value=dict(os.environ)):
            pid, _ = self.spawner.spawn_agent("golden", "matrix", "test-agent", "test-agent", "sibling-pod",
                                              {"src_embed": base64.b64encode(source.encode()).decode()})
        self.addCleanup(self.stop_child, pid)
        for _ in range(100):
            if marker.exists():
                break
            time.sleep(0.02)
        self.assertTrue(marker.exists())
        self.assertEqual(marker.read_text(), "trusted")

    def test_embedded_agent_imports_core_without_writable_pod_shadow(self):
        core = Path(self.tmp.name) / "core"
        core.mkdir(exist_ok=True)
        (core / "__init__.py").write_text("")
        (core / "magic.py").write_text("VALUE = 'trusted'\n")
        marker = Path(self.tmp.name) / "embedded-import"
        source = ("from pathlib import Path\nfrom core.magic import VALUE\n"
                  "Path(%r).write_text(VALUE)\n") % str(marker)
        with patch("core.python_core.core_spawner.build_encrypted_spawn_env", return_value=dict(os.environ)):
            pid, _ = self.spawner.spawn_agent("golden", "matrix", "test-agent", "test-agent", "embedded-pod",
                {"src_embed": base64.b64encode(source.encode()).decode()}, defer_gate=True)
        self.addCleanup(self.stop_child, pid)
        fake_core = Path(self.spawner.pm.session.runtime_pod_path) / "embedded-pod/core"
        fake_core.mkdir()
        (fake_core / "__init__.py").write_text("")
        (fake_core / "magic.py").write_text("VALUE = 'shadow'\n")
        self.spawner.release_pending_gate()
        for _ in range(100):
            if marker.exists():
                break
            time.sleep(0.02)
        self.assertTrue(marker.exists())
        self.assertEqual(marker.read_text(), "trusted")

    def test_sealed_source_survives_run_file_mutation_in_both_modes(self):
        for protected in (False, True):
            with self.subTest(protected=protected):
                marker = Path(self.tmp.name) / ("protected.json" if protected else "normal.json")
                source = ("import ctypes,json,sys\n"
                          "from pathlib import Path\n"
                          "Path(%r).write_text(json.dumps({'file':__file__,'argv':sys.argv,'main':__name__,'package':__package__,'dumpable':ctypes.CDLL(None).prctl(3,0,0,0,0)}))\n") % str(marker)
                pod = "pod-protected" if protected else "pod-normal"
                self.spawner.protect_memory = protected
                with patch("core.python_core.core_spawner.build_encrypted_spawn_env", return_value=dict(os.environ)):
                    pid, _ = self.spawner.spawn_agent("golden", "matrix", "test-agent", "test-agent", pod,
                        {"src_embed": base64.b64encode(source.encode()).decode()}, defer_gate=True)
                self.addCleanup(self.stop_child, pid)
                run_path = Path(self.spawner.pm.session.runtime_pod_path) / pod / "run"
                run_path.write_text("raise RuntimeError('replaced')")
                self.spawner.release_pending_gate()
                for _ in range(100):
                    if marker.exists():
                        break
                    time.sleep(0.02)
                self.assertTrue(marker.exists(), "verified source did not execute")
                result = json.loads(marker.read_text())
                self.assertEqual(result["main"], "__main__")
                self.assertEqual(result["file"], str(run_path))
                self.assertEqual(result["argv"], [str(run_path), "--job", "golden:test-agent"])
                if protected:
                    self.assertEqual(result["dumpable"], 0)
                    self.assertEqual(result["package"], "")
                else:
                    self.assertIsNone(result["package"])

    def test_encrypted_vault_is_consumed_by_real_fd_launcher(self):
        from core.python_core.mixin.ghost_vault import generate_agent_keypair
        keys = generate_agent_keypair()
        self.spawner._keychain.update(pub=keys["pub"], priv=keys["priv"],
                                      matrix_pub=keys["pub"], matrix_priv=keys["priv"])
        for protected in (False, True):
            with self.subTest(protected=protected):
                self.spawner.protect_memory = protected
                pod = "vault-protected" if protected else "vault-normal"
                marker = Path(self.tmp.name) / (pod + "-consumed")
                source = ("import os,sys\nfrom pathlib import Path\n"
                          "sys.path.insert(0, %r)\n"
                          "from core.python_core.mixin.ghost_vault import decrypt_vault\n"
                          "fd=int(os.environ['MATRIX_VAULT_DIR_FD'])\n"
                          "payload=decrypt_vault()\n"
                          "try: os.fstat(fd); closed=False\n"
                          "except OSError: closed=True\n"
                          "Path(%r).write_text(payload['args']['universal_id'] + ':' + str(closed))\n") % (str(ROOT / "matrixos"), str(marker))
                pid, _ = self.spawner.spawn_agent("golden", "matrix", "test-agent", "test-agent", pod,
                                                  {"src_embed": base64.b64encode(source.encode()).decode()})
                self.addCleanup(self.stop_child, pid)
                for _ in range(200):
                    if marker.exists():
                        break
                    time.sleep(0.02)
                self.assertTrue(marker.exists(), "child could not decrypt its pinned vault")
                self.assertEqual(marker.read_text(), "test-agent:True")
                self.assertFalse((Path(self.spawner.pm.session.runtime_pod_path) / pod / "vault").exists())


if __name__ == "__main__":
    unittest.main()
