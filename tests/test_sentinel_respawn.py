"""A refused respawn must remain visible and eligible for retry."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
path = ROOT / "matrixos/agents/python_core/sentinel/sentinel.py"
spec = importlib.util.spec_from_file_location("sentinel_respawn_test", path)
module = importlib.util.module_from_spec(spec)
with patch.dict(os.environ, {"SITE_ROOT": str(ROOT / "matrixos"), "AGENT_PATH": str(ROOT / "matrixos/agents/python_core")}):
    spec.loader.exec_module(module)


class SentinelRespawnTests(unittest.TestCase):
    def run_cycle(self, result):
        agent = module.Agent.__new__(module.Agent)
        agent.universal_id_under_watch = "target"
        agent.security_box = {"node": {"universal_id": "target", "name": "matrix", "vault": {}},
                              "matrix_priv": "key", "spawner": "sentinel"}
        agent.swarm_key = "key"
        agent.matrix_pub = "key"
        agent.encryption_enabled = False
        agent.running = True
        agent.command_line_args = {"universe": "test"}
        agent.path_resolution = {"comm_path": "/nonexistent-test-comm"}
        agent._last_run_log = 0
        agent._emit_beacon_watch_cycle = Mock()
        agent.log = Mock()
        agent.clear_to_spawn = Mock(return_value=True)
        agent.spawn_agent_direct = Mock(return_value=result)
        with patch.object(module, "interruptible_sleep", side_effect=lambda *_: setattr(agent, "running", False)):
            agent.watch_cycle()
        return agent

    def test_refused_spawn_is_reported_as_retry_not_success(self):
        agent = self.run_cycle(None)
        messages = [call.args[0] for call in agent.log.call_args_list if call.args]
        self.assertTrue(any("not started" in message and "retry" in message for message in messages))
        self.assertFalse(any("respawned successfully" in message for message in messages))
        agent.spawn_agent_direct.assert_called_once()

    def test_started_spawn_is_reported_as_success(self):
        agent = self.run_cycle((1234, ["python"]))
        messages = [call.args[0] for call in agent.log.call_args_list if call.args]
        self.assertTrue(any("respawned successfully" in message for message in messages))
        self.assertFalse(any("not started" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
