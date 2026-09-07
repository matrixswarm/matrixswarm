"""Tests for Harvester's local/SSH matrixd observation policy."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARVESTER = ROOT / "matrixos" / "agents" / "python_core" / "harvester"
POLICY_PATH = HARVESTER / "policy.py"
AGENT_PATH = HARVESTER / "harvester.py"
SSH_PATH = HARVESTER / "ssh_transport.py"
META_PATH = ROOT / "phoenix" / "agents_meta" / "harvester.json"
EDITOR_PATH = (
    ROOT
    / "phoenix"
    / "matrix_gui"
    / "swarm_workspace"
    / "cls_lib"
    / "agent"
    / "config_editors"
    / "harvester.py"
)

SPEC = importlib.util.spec_from_file_location("harvester_policy", POLICY_PATH)
assert SPEC and SPEC.loader
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
try:
    SSH_SPEC = importlib.util.spec_from_file_location("harvester_ssh", SSH_PATH)
    assert SSH_SPEC and SSH_SPEC.loader
    SSH = importlib.util.module_from_spec(SSH_SPEC)
    SSH_SPEC.loader.exec_module(SSH)
except ModuleNotFoundError as exc:
    if exc.name != "paramiko":
        raise
    SSH = None


def target(**overrides):
    value = {
        "id": "phoenix-primary",
        "universe": "phoenix",
        "minimum_agents": 6,
        "failure_threshold": 2,
        "recovery_threshold": 2,
        "alert_cooldown_sec": 30,
    }
    value.update(overrides)
    return POLICY.normalize_target(value)


class HarvesterPolicyTests(unittest.TestCase):
    def test_matrixd_snapshot_drives_universe_health(self):
        snapshot = POLICY.parse_matrixd_snapshot(
            json.dumps(
                {
                    "version": 1,
                    "universes": [
                        {
                            "universe": "phoenix",
                            "status": "active",
                            "agent_count": 6,
                        }
                    ],
                }
            )
        )
        self.assertEqual(
            POLICY.observation_for_target(target(), snapshot),
            (True, "ACTIVE_6_AGENTS"),
        )
        self.assertEqual(
            POLICY.observation_for_target(target(minimum_agents=7), snapshot),
            (False, "AGENTS_6_BELOW_7"),
        )
        self.assertEqual(
            POLICY.observation_for_target(target(universe="missing"), snapshot),
            (False, "UNIVERSE_ABSENT"),
        )

    def test_snapshot_rejects_unbounded_or_untrusted_shapes(self):
        bad = [
            "not json",
            '{"version":2,"universes":[]}',
            '{"version":1,"universes":[{"universe":"../bad","status":"active","agent_count":1}]}',
            '{"version":1,"universes":[{"universe":"good","status":"dead","agent_count":1}]}',
        ]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(
                POLICY.HarvesterPolicyError
            ):
                POLICY.parse_matrixd_snapshot(payload)
        with self.assertRaises(POLICY.HarvesterPolicyError):
            target(universe="not.allowed")
        with self.assertRaises(POLICY.HarvesterPolicyError):
            target(universe="x" * 33)

    def test_failures_and_recoveries_are_debounced(self):
        policy = target()
        state = POLICY.initial_state()
        state, event = POLICY.evaluate_observation(
            state, success=False, observed_at=10, target=policy
        )
        self.assertIsNone(event)
        state, event = POLICY.evaluate_observation(
            state, success=False, observed_at=11, target=policy
        )
        self.assertEqual(event, "DOWN")
        state, event = POLICY.evaluate_observation(
            state, success=True, observed_at=12, target=policy
        )
        self.assertIsNone(event)
        state, event = POLICY.evaluate_observation(
            state, success=True, observed_at=13, target=policy
        )
        self.assertEqual(event, "RECOVERY")

    def test_transport_is_fixed_and_host_key_pinned(self):
        source = SSH_PATH.read_text(encoding="utf-8")
        self.assertIn("matrixd list --json", source)
        self.assertIn("/usr/bin/sudo -n", source)
        self.assertIn("_PinnedPolicy", source)
        self.assertIn("hmac.compare_digest", source)
        self.assertIn('"look_for_keys": False', source)
        self.assertNotIn("AutoAddPolicy", source)
        self.assertNotIn("StrictHostKeyChecking=no", source)
        self.assertNotIn("sshpass", source)
        self.assertNotIn("matrixd boot", source)
        self.assertNotIn("swarm_key", source)

        if SSH is not None:
            self.assertIn("matrixd list --json", SSH.MATRIXD_LIST_COMMAND)

    def test_agent_executes_only_fixed_local_matrixd_argv(self):
        source = AGENT_PATH.read_text(encoding="utf-8")
        self.assertIn('"/matrix/scripts/matrixd",', source)
        self.assertIn('"list",', source)
        self.assertIn('"--json",', source)
        self.assertIn("shell=False", source)
        self.assertNotIn('"kill",', source)
        self.assertNotIn("matrixd boot", source)
        self.assertNotIn("swarm_key", source)
        self.assertIn("len(value) > 1", source)

    def test_phoenix_metadata_is_inert_and_editor_compiles(self):
        metadata = json.loads(META_PATH.read_text(encoding="utf-8"))
        self.assertEqual(metadata["name"], "harvester")
        self.assertEqual(metadata["config"]["mode"], "ssh")
        self.assertIs(metadata["config"]["enabled"], False)
        self.assertEqual(metadata["config"]["targets"], [])
        constraint_names = [next(iter(item)) for item in metadata["constraints"]]
        self.assertIn("ssh", constraint_names)
        ssh_constraint = metadata["constraints"][constraint_names.index("ssh")]
        self.assertIs(ssh_constraint["ssh"], None)
        compile(
            EDITOR_PATH.read_text(encoding="utf-8"),
            str(EDITOR_PATH),
            "exec",
        )
        editor_source = EDITOR_PATH.read_text(encoding="utf-8")
        self.assertIn("VaultCoreSingleton", editor_source)
        self.assertNotIn("add_constraint", editor_source)
        self.assertNotIn("remove_constraint", editor_source)
        self.assertNotIn("ssh_serial", editor_source)
        self.assertNotIn("swarm_key", editor_source)
        self.assertNotIn("automatic_recovery", editor_source)

    def test_matrixd_exposes_bounded_json_list_mode(self):
        source = (ROOT / "matrixos" / "scripts" / "matrixd").read_text(
            encoding="utf-8"
        )
        self.assertIn('list_cmd.add_argument("--json"', source)
        self.assertIn('return {"version": 1, "universes": snapshot}', source)
        snapshot_source = source[
            source.index("def universe_snapshot"):source.index("def list_universes")
        ]
        self.assertNotIn('"details"', snapshot_source)
        self.assertNotIn('"cmd"', snapshot_source)


if __name__ == "__main__":
    unittest.main()
