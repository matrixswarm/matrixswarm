"""A failed or stale Reaper stage must never advance a transaction."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
from core.python_core.mixin.reap_status_handler import ReapStatusHandlerMixin
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject


class Probe(ReapStatusHandlerMixin):
    def __init__(self):
        self.node = {"universal_id": "target", "lifecycle_status": {
            "transaction_id": "tx", "op_stage": "restart_wait", "success": True,
            "reported_stage": "restart_start",
            "agent_status_callback": {"operation": "restart_subtree"}}}
        self.tree = SimpleNamespace(nodes={"target": self.node}, get_node=lambda uid: self.node if uid == "target" else None)
        self.meta = {"swarm_state": {"reserved_agent_ids": {"reaper": "reaper"}}}
        self.messages = []
    def verify_identity(self, *_): return True
    def get_agent_tree_master(self): return self.tree
    def save_agent_tree_master(self): return True
    def log(self, message="", **kwargs): self.messages.append(str(message))


class ReaperStageSafetyTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("core.python_core.mixin.reap_status_handler.commit_reap_mutation")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_failed_later_stage_does_not_reuse_previous_success(self):
        agent = Probe()
        agent.cmd_reap_status.__wrapped__(agent, {"universal_id": "target", "transaction_id": "tx", "stage": "restart_wait",
                               "result": {"success": False, "state": "alive"}}, {}, IdentityObject(True, "reaper"))
        life = agent.node["lifecycle_status"]
        self.assertFalse(life["success"])
        self.assertFalse(agent._transaction_checkpoint.__wrapped__(agent, "tx", "restart_wait", None, "restart_cleanup"))
        self.assertEqual(life["op_stage"], "restart_wait")

    def test_success_with_unacceptable_state_does_not_advance(self):
        agent = Probe()
        agent.cmd_reap_status.__wrapped__(agent, {"universal_id": "target", "transaction_id": "tx", "stage": "restart_wait",
                               "result": {"success": True, "state": "alive"}}, {}, IdentityObject(True, "reaper"))
        self.assertFalse(agent._transaction_checkpoint.__wrapped__(agent, "tx", "restart_wait", None, "restart_cleanup"))
        self.assertEqual(agent.node["lifecycle_status"]["op_stage"], "restart_wait")

    def test_valid_stage_advances_and_resets_success(self):
        agent = Probe()
        agent.cmd_reap_status.__wrapped__(agent, {"universal_id": "target", "transaction_id": "tx", "stage": "restart_wait",
                               "result": {"success": True, "state": "pod_cleared"}}, {}, IdentityObject(True, "reaper"))
        self.assertTrue(agent._transaction_checkpoint.__wrapped__(agent, "tx", "restart_wait", None, "restart_cleanup"))
        life = agent.node["lifecycle_status"]
        self.assertEqual(life["op_stage"], "restart_cleanup")
        self.assertFalse(life["success"])

    def test_stale_or_non_boolean_status_cannot_overwrite_current_stage(self):
        agent = Probe()
        original = dict(agent.node["lifecycle_status"])
        for stage, success in (("restart_start", True), ("restart_wait", "true")):
            agent.cmd_reap_status.__wrapped__(agent, {"universal_id": "target", "transaction_id": "tx", "stage": stage,
                                   "result": {"success": success, "state": "pod_cleared"}}, {}, IdentityObject(True, "reaper"))
            self.assertEqual(agent.node["lifecycle_status"], original)

    def test_delayed_status_from_previous_transaction_is_ignored(self):
        agent = Probe()
        original = dict(agent.node["lifecycle_status"])
        agent.cmd_reap_status.__wrapped__(agent, {"universal_id": "target", "transaction_id": "old-tx", "stage": "restart_wait",
                               "result": {"success": True, "state": "pod_cleared"}}, {}, IdentityObject(True, "reaper"))
        self.assertEqual(agent.node["lifecycle_status"], original)

    def test_probe_requires_and_retains_target_snapshot(self):
        agent = Probe()
        life = agent.node["lifecycle_status"]
        life["op_stage"] = "shutdown_probe"
        agent.cmd_reap_status.__wrapped__(agent, {"universal_id": "target", "transaction_id": "tx", "stage": "shutdown_probe",
                               "result": {"success": True, "state": "alive"}}, {}, IdentityObject(True, "reaper"))
        self.assertFalse(life["success"])
        self.assertEqual(life["op_stage"], "shutdown_probe")
        snapshot = [{"pod": "pod1", "pid": 42, "process_started_at": 1.0, "record_sha256": "a" * 64}]
        agent.cmd_reap_status.__wrapped__(agent, {"universal_id": "target", "transaction_id": "tx", "stage": "shutdown_probe",
                               "result": {"success": True, "state": "alive", "target_snapshot": snapshot}}, {}, IdentityObject(True, "reaper"))
        snapshot[0]["pid"] = 99
        self.assertEqual(life["reap_target"][0]["pid"], 42)
        self.assertEqual(life["op_stage"], "_shutdown_probe")

    def test_matrix_challenge_authorizes_only_current_transaction_and_stage(self):
        agent = Probe()
        life = agent.node["lifecycle_status"]
        life.update({"op": "shutdown_restart", "locked": {"by": "matrix"}, "reap_target": []})
        packets = []
        class Packet:
            def set_data(self, payload): packets.append(payload)
        agent.get_delivery_packet = lambda *_: Packet()
        agent.pass_packet = lambda packet, uid: uid == "reaper"
        agent._runtime_comm_fd = 1
        agent.matrix_pub = "fixture"
        agent.command_line_args = {"universe": "u"}
        agent.path_resolution = {"reboot_uuid": "boot"}
        request = {"universal_id": "target", "transaction_id": "tx", "stage": "restart_wait", "nonce": "a" * 64}
        state = {"revision": "b" * 64, "targets": {"target": {"transaction_id": "tx", "stage": "restart_wait", "op": "shutdown_restart", "locked": True, "target_snapshot": []}}}
        with patch("core.python_core.mixin.reap_status_handler.read_reap_authorization", return_value=(state, b"")):
            agent.cmd_reap_authorize(request, {}, IdentityObject(True, "other"))
            self.assertEqual(packets, [])
            agent.cmd_reap_authorize(request, {}, IdentityObject(True, "reaper"))
            self.assertTrue(packets[-1]["content"]["authorized"])
            self.assertEqual(packets[-1]["content"]["nonce"], "a" * 64)
            self.assertEqual(packets[-1]["content"]["revision"], "b" * 64)
            agent.cmd_reap_authorize({**request, "transaction_id": "old"}, {}, IdentityObject(True, "reaper"))
            self.assertFalse(packets[-1]["content"]["authorized"])
            agent.cmd_reap_authorize({**request, "stage": "restart_start"}, {}, IdentityObject(True, "reaper"))
            self.assertFalse(packets[-1]["content"]["authorized"])


if __name__ == "__main__":
    unittest.main()
