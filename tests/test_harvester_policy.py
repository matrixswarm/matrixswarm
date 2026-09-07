"""Tests for Harvester's local/SSH matrixd observation policy."""

from __future__ import annotations

import base64
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
ASSIGNMENT_EDITOR_PATH = (
    ROOT
    / "phoenix"
    / "matrix_gui"
    / "registry"
    / "object_classes"
    / "editors"
    / "harvester_assignment.py"
)
ASSIGNMENT_PROVIDER_PATH = (
    ROOT
    / "phoenix"
    / "matrix_gui"
    / "registry"
    / "object_classes"
    / "providers"
    / "harvester_assignment.py"
)
SSH_EDITOR_PATH = (
    ROOT
    / "phoenix"
    / "matrix_gui"
    / "registry"
    / "object_classes"
    / "editors"
    / "ssh.py"
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
        "recovery_mode": "disabled",
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

    def test_resurrection_is_explicit_double_gated_and_bounded(self):
        policy = target(
            recovery_mode="automatic",
            linux_user="matrix-phoenix",
            directive_path="/matrix/boot_directives/phoenix.enc.json",
            swarm_key=base64.b64encode(b"x" * 32).decode("ascii"),
            recovery_attempt_limit=2,
            recovery_cooldown_sec=60,
        )
        state = POLICY.initial_state()
        state.update(status="down")
        self.assertFalse(
            POLICY.recovery_due(
                state,
                policy,
                globally_enabled=False,
                collection_available=True,
                observed_at=100,
            )
        )
        self.assertTrue(
            POLICY.recovery_due(
                state,
                policy,
                globally_enabled=True,
                collection_available=True,
                observed_at=100,
            )
        )
        state = POLICY.record_recovery_attempt(state, observed_at=100)
        self.assertFalse(
            POLICY.recovery_due(
                state,
                policy,
                globally_enabled=True,
                collection_available=True,
                observed_at=159,
            )
        )
        self.assertTrue(
            POLICY.recovery_due(
                state,
                policy,
                globally_enabled=True,
                collection_available=True,
                observed_at=160,
            )
        )
        state = POLICY.record_recovery_attempt(state, observed_at=160)
        self.assertFalse(
            POLICY.recovery_due(
                state,
                policy,
                globally_enabled=True,
                collection_available=True,
                observed_at=1_000,
            )
        )

    def test_resurrection_requires_exact_directive_and_valid_key(self):
        automatic = {
            "recovery_mode": "automatic",
            "linux_user": "matrix-phoenix",
            "swarm_key": base64.b64encode(b"x" * 32).decode("ascii"),
        }
        policy = target(**automatic)
        self.assertEqual(
            policy["directive_path"],
            "/matrix/boot_directives/phoenix.enc.json",
        )
        with self.assertRaises(POLICY.HarvesterPolicyError):
            target(**(automatic | {"directive_path": "/tmp/phoenix.enc.json"}))
        with self.assertRaises(POLICY.HarvesterPolicyError):
            target(
                **(
                    automatic
                    | {
                        "directive_path": (
                            "/matrix/unused/../boot_directives/phoenix.enc.json"
                        )
                    }
                )
            )
        with self.assertRaises(POLICY.HarvesterPolicyError):
            target(**(automatic | {"swarm_key": "not-a-key"}))

    def test_transport_is_fixed_and_host_key_pinned(self):
        source = SSH_PATH.read_text(encoding="utf-8")
        self.assertIn("matrixd list --json", source)
        self.assertIn("run_matrixd_boot", source)
        self.assertIn("stdin.write", source)
        self.assertIn("test -f", source)
        self.assertIn("/usr/bin/sudo -n", source)
        self.assertIn("_PinnedPolicy", source)
        self.assertIn("hmac.compare_digest", source)
        self.assertIn('"look_for_keys": False', source)
        self.assertNotIn("AutoAddPolicy", source)
        self.assertNotIn("StrictHostKeyChecking=no", source)
        self.assertNotIn("sshpass", source)

        if SSH is not None:
            self.assertIn("matrixd list --json", SSH.MATRIXD_LIST_COMMAND)
            policy = target(
                recovery_mode="automatic",
                linux_user="matrix-phoenix",
                swarm_key=base64.b64encode(b"k" * 32).decode("ascii"),
            )
            command = SSH._remote_boot_command(policy)
            self.assertNotIn(policy["swarm_key"], command)
            self.assertIn("matrixd boot", command)
            self.assertIn("test -f", command)

    def test_agent_uses_only_fixed_matrixd_operations(self):
        source = AGENT_PATH.read_text(encoding="utf-8")
        self.assertIn('"/matrix/scripts/matrixd",', source)
        self.assertIn('"list",', source)
        self.assertIn('"--json",', source)
        self.assertIn("shell=False", source)
        self.assertNotIn('"kill",', source)
        self.assertIn("run_matrixd_boot", source)
        self.assertIn("len(value) > 1", source)

    def test_phoenix_metadata_uses_harvester_assignment_constraint(self):
        metadata = json.loads(META_PATH.read_text(encoding="utf-8"))
        self.assertEqual(metadata["name"], "harvester")
        self.assertNotIn("mode", metadata["config"])
        self.assertIs(metadata["config"]["enabled"], False)
        self.assertEqual(metadata["config"]["targets"], [])
        constraint_names = [next(iter(item)) for item in metadata["constraints"]]
        self.assertNotIn("ssh", constraint_names)
        self.assertIn("harvester_assignment", constraint_names)
        assignment = metadata["constraints"][
            constraint_names.index("harvester_assignment")
        ]
        self.assertIs(assignment["harvester_assignment"], None)

    def test_phoenix_editors_keep_assignment_separate_from_runtime_policy(self):
        for path in (
            EDITOR_PATH,
            ASSIGNMENT_EDITOR_PATH,
            ASSIGNMENT_PROVIDER_PATH,
            SSH_EDITOR_PATH,
        ):
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        editor_source = EDITOR_PATH.read_text(encoding="utf-8")
        self.assertNotIn("VaultCoreSingleton", editor_source)
        self.assertNotIn("swarm_key", editor_source)
        assignment_source = ASSIGNMENT_EDITOR_PATH.read_text(encoding="utf-8")
        self.assertIn("VaultCoreSingleton", assignment_source)
        self.assertIn('"Contact only", "contact_only"', assignment_source)
        self.assertIn("Contact + resurrect", assignment_source)
        self.assertIn('"ssh": ssh_fields', assignment_source)
        serialize_source = assignment_source[
            assignment_source.index("def serialize"):
            assignment_source.index("def deploy_fields")
        ]
        self.assertNotIn("swarm_key", serialize_source)
        self.assertNotIn("password", serialize_source)
        ssh_editor_source = SSH_EDITOR_PATH.read_text(encoding="utf-8")
        deploy_source = ssh_editor_source[
            ssh_editor_source.index("def deploy_fields"):
            ssh_editor_source.index("def on_load")
        ]
        self.assertIn('out["sensitive_fields"]', deploy_source)
        self.assertNotIn(
            'out[\'sensitive_fields\']={"username": "1", "password": "1", '
            '"private_key": "1", "private_key_passphrase": "1"},',
            ssh_editor_source,
        )

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
