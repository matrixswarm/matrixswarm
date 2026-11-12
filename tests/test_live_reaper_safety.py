"""In-swarm Reaper never trusts PID hints or follows destructive paths."""
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
from core.python_core.class_lib.processes.b2_bomber import ProcessIdentityUnavailable
from core.python_core.lifecycle_fence import LifecycleFence

spec = importlib.util.spec_from_file_location("live_reaper_test", ROOT / "matrixos/agents/python_core/reaper/reaper.py")
module = importlib.util.module_from_spec(spec)
with patch.dict(os.environ, {"SITE_ROOT": str(ROOT / "matrixos"), "AGENT_PATH": str(ROOT / "matrixos/agents/python_core")}):
    spec.loader.exec_module(module)


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux lifecycle fence required")
class LiveReaperSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.boot = "20261111_123456"
        self.generation = "a" * 32
        lockdir = self.base / "universes/lifecycle/u"
        lockdir.mkdir(parents=True)
        for directory in (lockdir, lockdir.parent, lockdir.parent.parent):
            directory.chmod(0o700)
        (lockdir / "lock").touch(mode=0o600)
        (lockdir / "lock").chmod(0o660)
        fence = LifecycleFence(self.base, "u", _owner_uid=os.getuid())
        with fence.exclusive():
            fence.write_state("ACTIVE", self.generation, self.boot)
        runtime = self.base / "universes/runtime/u" / self.boot
        self.pod_root, self.comm_root = runtime / "pod", runtime / "comm"
        self.pod_root.mkdir(parents=True)
        self.comm_root.mkdir()
        self.agent = module.Agent.__new__(module.Agent)
        self.agent.command_line_args = {"universe": "u", "universal_id": "reaper"}
        self.agent.path_resolution = {"install_path": str(self.base), "pod_path": str(self.pod_root), "comm_path": str(self.comm_root)}
        self.agent.get_matrix_universal_id = lambda: "matrix"
        self.agent._verified_matrix = lambda *_: True
        self.agent.log = Mock()
        self.agent._report_to_matrix = Mock()
        self.agent._visible_target_jobs = Mock(return_value=set())
        self.expected_snapshot = []
        self.agent._authorization_lock = threading.Lock()
        self.agent._authorization_pending = {}
        self.agent._authorization_inflight = set()
        self.agent._verify_committed_authorization = Mock()
        self.agent._request_authorization = lambda uid, stage, transaction_id: self.agent._execute_authorized(
            uid, stage, transaction_id, None if stage == "shutdown_probe" else self.expected_snapshot, "a" * 64)
        self.patcher = patch("core.python_core.class_lib.processes.reaper.LifecycleFence",
                             side_effect=lambda base, uid: LifecycleFence(base, uid, _owner_uid=os.getuid()))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.env = patch.dict(os.environ, {"MATRIX_LIFECYCLE_GENERATION": self.generation})
        self.env.start()
        self.addCleanup(self.env.stop)

    def record(self, uid="target", pid=123):
        pod = self.pod_root / "pod1"
        pod.mkdir()
        (pod / "boot.json").write_text(json.dumps({"universal_id": uid, "pid": pid,
            "process_started_at": 123.0, "cmd": ["python", "launcher", "--job", f"u:{uid}"]}))
        self.snapshot_record(pod)
        return pod

    def snapshot_record(self, pod):
        record = json.loads((pod / "boot.json").read_text())
        digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.expected_snapshot = [{"pod": pod.name, "pid": record["pid"],
                                   "process_started_at": record["process_started_at"], "record_sha256": digest}]

    def dispatch(self, stage, **hints):
        target = {"universal_id": "target", "op_stage": stage, "transaction_id": "tx", **hints}
        self.agent.cmd_reap_agents({"targets": [target]}, {}, None)
        return self.agent._report_to_matrix.call_args

    def test_restart_start_ignores_untrusted_pid_hints(self):
        self.record()
        ref = Mock(pid=123)
        ref.is_alive.return_value = True
        self.agent._visible_target_jobs.return_value = {123}
        with patch.object(module, "PinnedProcess", return_value=ref) as pin:
            report = self.dispatch("restart_start", pid=999999, pod_path="/outside")
        self.assertEqual(pin.call_args.args[0], 123)
        self.assertTrue(report.args[2])
        self.assertEqual(report.kwargs["extra"]["state"], "alive")
        self.assertTrue((self.comm_root / "target/incoming/die").is_file())
        ref.close.assert_called_once()

    def test_unrecorded_live_process_or_reused_pid_fails_closed(self):
        self.record()
        self.agent._visible_target_jobs.return_value = {999}
        ref = Mock(pid=123)
        ref.is_alive.return_value = False
        with patch.object(module, "PinnedProcess", return_value=ref):
            report = self.dispatch("delete_cleanup")
        self.assertFalse(report.args[2])
        self.assertTrue((self.pod_root / "pod1/boot.json").exists())
        with patch.object(module, "PinnedProcess", side_effect=ProcessIdentityUnavailable("PID reused")):
            report = self.dispatch("delete_escalate", pid=123)
        self.assertFalse(report.args[2])
        self.assertTrue((self.pod_root / "pod1/boot.json").exists())

    def test_stale_reaper_generation_cannot_touch_target(self):
        pod = self.record()
        with patch.dict(os.environ, {"MATRIX_LIFECYCLE_GENERATION": "b" * 32}):
            report = self.dispatch("delete_cleanup")
        self.assertFalse(report.args[2])
        self.assertTrue((pod / "boot.json").exists())

    def test_restart_escalation_signals_only_pinned_process_then_cleans(self):
        pod = self.record()
        (self.comm_root / "target/incoming").mkdir(parents=True)
        (self.comm_root / "target/incoming/die").write_text("terminate")
        active = {"value": True}
        class Ref:
            pid = 123
            def __init__(self, *args, **kwargs): pass
            def is_alive(self): return active["value"]
            def send_signal(self, sig): active["value"] = False
            def kill(self): self.fail("already stopped")
            def close(self): pass
        self.agent._visible_target_jobs.side_effect = lambda uid: {123} if active["value"] else set()
        with patch.object(module, "PinnedProcess", Ref), patch.object(module.time, "sleep"):
            report = self.dispatch("restart_wait")
        self.assertTrue(report.args[2])
        self.assertEqual(report.kwargs["extra"]["state"], "pod_cleared")
        self.assertFalse(pod.exists())
        self.assertFalse((self.comm_root / "target/incoming/die").exists())
        self.assertTrue((self.comm_root / "target").is_dir())

    def test_real_process_is_stopped_and_its_pod_cleaned(self):
        process = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)", "--job", "u:target"])
        self.addCleanup(lambda: process.wait(timeout=3))
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        pod = self.record(pid=process.pid)
        boot = pod / "boot.json"
        data = json.loads(boot.read_text())
        data["cmd"] = psutil.Process(process.pid).cmdline()
        data["process_started_at"] = psutil.Process(process.pid).create_time()
        boot.write_text(json.dumps(data))
        self.snapshot_record(pod)
        self.agent._visible_target_jobs.side_effect = lambda uid: {process.pid} if process.poll() is None else set()
        real_sleep = time.sleep
        with patch.object(module.time, "sleep", side_effect=lambda _: real_sleep(0.1)):
            report = self.dispatch("restart_wait")
        self.assertTrue(report.args[2], report.kwargs)
        self.assertEqual(report.kwargs["extra"]["state"], "pod_cleared")
        self.assertIsNotNone(process.poll())
        self.assertFalse(pod.exists())

    def test_cleanup_mount_error_never_reports_success_or_removes_data(self):
        pod = self.record()
        ref = Mock(pid=123)
        ref.is_alive.return_value = False
        with patch.object(module, "PinnedProcess", return_value=ref), \
             patch.object(module, "_tree_preflight", side_effect=OSError(errno.EXDEV, "mount")):
            report = self.dispatch("delete_cleanup")
        self.assertFalse(report.args[2])
        self.assertTrue((pod / "boot.json").exists())

    def test_new_pod_appearing_during_preflight_blocks_cleanup(self):
        pod = self.record()
        ref = Mock(pid=123)
        ref.is_alive.return_value = False
        appeared = []
        def preflight(_fd):
            if not appeared:
                new = self.pod_root / "pod2"
                new.mkdir()
                (new / "boot.json").write_text(json.dumps({"universal_id": "target", "pid": 456,
                    "process_started_at": 456.0, "cmd": ["python", "launcher", "--job", "u:target"]}))
                appeared.append(True)
        with patch.object(module, "PinnedProcess", return_value=ref), patch.object(module, "_tree_preflight", side_effect=preflight):
            report = self.dispatch("delete_cleanup")
        self.assertFalse(report.args[2])
        self.assertTrue((pod / "boot.json").exists())
        self.assertTrue((self.pod_root / "pod2/boot.json").exists())

    def test_symlinked_target_comm_cannot_redirect_die(self):
        self.record()
        outside = self.base / "outside"
        outside.mkdir()
        (self.comm_root / "target").symlink_to(outside, target_is_directory=True)
        ref = Mock(pid=123)
        ref.is_alive.return_value = True
        self.agent._visible_target_jobs.return_value = {123}
        with patch.object(module, "PinnedProcess", return_value=ref):
            report = self.dispatch("restart_start")
        self.assertFalse(report.args[2])
        self.assertEqual(list(outside.iterdir()), [])

    def test_reaper_echoes_transaction_and_rejects_missing_identity(self):
        payloads = []
        class Packet:
            def set_data(self, data): payloads.append(data)
        self.agent.get_delivery_packet = lambda *_: Packet()
        self.agent.pass_packet = lambda *args: True
        module.Agent._report_to_matrix(self.agent, "target", "restart_wait", True,
                                       transaction_id="tx-123", extra={"state": "pod_cleared"})
        self.assertEqual(payloads[0]["content"]["transaction_id"], "tx-123")
        self.agent.cmd_reap_agents({"targets": [{"universal_id": "target", "op_stage": "restart_start"}]}, {}, None)
        self.agent._report_to_matrix.assert_not_called()

    def test_replacement_process_is_rejected_against_authorized_snapshot(self):
        pod = self.record()
        boot = pod / "boot.json"
        replacement = json.loads(boot.read_text())
        replacement["pid"] = 456
        replacement["process_started_at"] = 456.0
        boot.write_text(json.dumps(replacement))
        ref = Mock(pid=456)
        ref.is_alive.return_value = True
        self.agent._visible_target_jobs.return_value = {456}
        with patch.object(module, "PinnedProcess", return_value=ref):
            self.agent.cmd_reap_agents({"targets": [{"universal_id": "target", "op_stage": "restart_start", "transaction_id": "tx"}]}, {}, None)
        self.assertFalse(self.agent._report_to_matrix.call_args.args[2])
        self.assertFalse((self.comm_root / "target/incoming/die").exists())
        self.assertTrue(boot.exists())

    def test_nonce_challenge_accepts_only_matching_fresh_proof_once(self):
        packets = []
        class Packet:
            def set_data(self, data): packets.append(data)
        self.agent.get_delivery_packet = lambda *_: Packet()
        self.agent.pass_packet = lambda *args: True
        self.agent._request_authorization = lambda *args: module.Agent._request_authorization(self.agent, *args)
        self.agent._execute_authorized = Mock()
        self.agent.cmd_reap_agents({"targets": [{"universal_id": "target", "op_stage": "restart_start", "transaction_id": "tx"}]}, {}, None)
        challenge = packets[0]["content"]
        proof = {**challenge, "authorized": True, "target_snapshot": [], "revision": "a" * 64}
        with patch.object(module.threading, "Thread") as worker:
            self.agent.cmd_reap_authorization({**proof, "transaction_id": "old"}, {}, None)
            worker.assert_not_called()
            self.agent.cmd_reap_authorization(proof, {}, None)
            worker.assert_called_once()
            self.agent.cmd_reap_authorization(proof, {}, None)
            worker.assert_called_once()  # replay cannot start another worker
            self.agent.cmd_reap_agents({"targets": [{"universal_id": "target", "op_stage": "restart_start", "transaction_id": "tx"}]}, {}, None)
            self.assertEqual(len(packets), 1)  # same stage remains in flight

    def test_expired_authorization_proof_never_executes(self):
        packets = []
        class Packet:
            def set_data(self, data): packets.append(data)
        self.agent.get_delivery_packet = lambda *_: Packet()
        self.agent.pass_packet = lambda *args: True
        self.agent._request_authorization = lambda *args: module.Agent._request_authorization(self.agent, *args)
        self.agent.cmd_reap_agents({"targets": [{"universal_id": "target", "op_stage": "restart_start", "transaction_id": "tx"}]}, {}, None)
        proof = {**packets[0]["content"], "authorized": True, "target_snapshot": [], "revision": "a" * 64}
        self.agent._authorization_pending[proof["nonce"]]["deadline"] = 0
        with patch.object(module.threading, "Thread") as worker:
            self.agent.cmd_reap_authorization(proof, {}, None)
            worker.assert_not_called()
        self.assertFalse(self.agent._report_to_matrix.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
