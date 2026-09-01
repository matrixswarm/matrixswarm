"""Tests for the reusable approval-gated cognitive-run state machine."""

from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))

from core.python_core.mixin.cognitive_run import (  # noqa: E402
    CognitiveRunError,
    CognitiveRunMixin,
)
from core.python_core.mixin.encrypted_state import EncryptedStateMixin  # noqa: E402


class _CognitiveAgent(EncryptedStateMixin, CognitiveRunMixin):
    def __init__(self, root: str, *, active: int = 2, retained: int = 8) -> None:
        self.command_line_args = {"universal_id": "operator-agent-1"}
        self.tree_node = {
            "config": {
                "security": {
                    "symmetric_encryption": {
                        "key": base64.b64encode(b"k" * 32).decode("ascii")
                    }
                }
            }
        }
        self.path_resolution = {"static_comm_path_resolved": root}
        self.init_encrypted_state(namespace="cognitive")
        self.init_cognitive_runs(
            max_active_runs=active,
            max_retained_runs=retained,
            default_turn_budget=2,
        )


class CognitiveRunMixinTests(unittest.TestCase):
    def _create(self, agent: _CognitiveAgent, run_id: str = "run-1") -> dict:
        return agent.create_cognitive_run(
            run_id,
            workflow_id="read_status",
            requested_by="request-broker-1",
            server_id="system_status",
            tool_name="read_status",
            arguments={"scope": "summary"},
        )

    def test_run_requires_approval_and_keeps_sensitive_payload_out_of_index(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = _CognitiveAgent(directory)
            run = self._create(agent)
            self.assertEqual(run["state"], "awaiting_approval")
            with self.assertRaisesRegex(CognitiveRunError, "cannot transition"):
                agent.mark_cognitive_dispatching("run-1", "mcp-run-1")

            index = agent.load_encrypted_state("run_index")
            self.assertEqual(index["runs"][0]["workflow_id"], "read_status")
            self.assertNotIn("arguments", index["runs"][0])
            checkpoint = agent.get_cognitive_run("run-1")
            self.assertEqual(checkpoint["mcp"]["arguments"], {"scope": "summary"})

    def test_approval_then_completion_persists_result_without_public_disclosure(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = _CognitiveAgent(directory)
            self._create(agent)
            agent.approve_cognitive_run("run-1", "approval-console-1")
            agent.mark_cognitive_dispatching("run-1", "operator-run-1")
            agent.complete_cognitive_run(
                "run-1", state="completed", result={"status": "green"}
            )
            checkpoint = agent.get_cognitive_run("run-1")
            self.assertEqual(checkpoint["state"], "completed")
            self.assertEqual(checkpoint["result"], {"status": "green"})
            self.assertEqual(
                agent.cognitive_run_summary("run-1"),
                {
                    "run_id": "run-1",
                    "workflow_id": "read_status",
                    "state": "completed",
                    "created_at": checkpoint["created_at"],
                    "updated_at": checkpoint["updated_at"],
                },
            )

    def test_restart_marks_inflight_run_for_manual_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            first = _CognitiveAgent(directory)
            self._create(first)
            first.approve_cognitive_run("run-1", "approval-console-1")
            first.mark_cognitive_dispatching("run-1", "operator-run-1")

            restarted = _CognitiveAgent(directory)
            recovered = restarted.get_cognitive_run("run-1")
            self.assertEqual(recovered["state"], "recovery_required")
            self.assertEqual(recovered["events"][-1]["event"], "recovery_required")
            with self.assertRaisesRegex(CognitiveRunError, "cannot transition"):
                restarted.mark_cognitive_dispatching("run-1", "replayed-run")

    def test_active_run_limit_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = _CognitiveAgent(directory, active=1)
            self._create(agent, "run-1")
            with self.assertRaisesRegex(CognitiveRunError, "active-run limit"):
                self._create(agent, "run-2")
            agent.deny_cognitive_run("run-1", "approval-console-1")
            self._create(agent, "run-2")

    def test_bad_or_oversized_results_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = _CognitiveAgent(directory)
            self._create(agent)
            agent.approve_cognitive_run("run-1", "approval-console-1")
            with self.assertRaisesRegex(CognitiveRunError, "JSON-compatible"):
                agent.complete_cognitive_run("run-1", state="completed", result={"bad": {1}})
            with self.assertRaisesRegex(CognitiveRunError, "exceeds"):
                agent.complete_cognitive_run("run-1", state="completed", result={"large": "x" * 131_073})


class OperatorAgentMetadataTests(unittest.TestCase):
    def test_operator_agent_is_inert_by_default_and_requires_signed_roles(self):
        import json

        metadata = json.loads(
            (ROOT / "phoenix" / "agents_meta" / "operator_agent.json").read_text(
                encoding="utf-8"
            )
        )
        config = metadata["config"]
        self.assertFalse(config["enabled"])
        self.assertEqual(config["authorized_requester_uids"], [])
        self.assertEqual(config["authorized_approver_uids"], [])
        self.assertEqual(config["workflows"], {})
        self.assertTrue(config["require_distinct_approver"])

    def test_operator_editor_policy_requires_two_identity_sets_and_fixed_workflow(self):
        sys.path.insert(0, str(ROOT / "phoenix"))
        from matrix_gui.swarm_workspace.cls_lib.agent.config_editors.operator_agent_model import (
            OperatorAgentConfigError,
            validated_operator_policy,
        )

        with self.assertRaisesRegex(OperatorAgentConfigError, "same identity"):
            validated_operator_policy(
                enabled=True,
                requesters=["operator-1"],
                approvers=["operator-1"],
                workflows={},
                limits={},
            )
        policy = validated_operator_policy(
            enabled=True,
            requesters=["requester-1"],
            approvers=["approver-1"],
            workflows={
                "read_status": {
                    "server_id": "status-server",
                    "tool_name": "read_status",
                    "arguments": {},
                    "requires_approval": True,
                    "turn_budget": 1,
                }
            },
            limits={},
        )
        self.assertTrue(policy["enabled"])
        self.assertTrue(policy["require_distinct_approver"])
        self.assertEqual(policy["workflows"]["read_status"]["arguments"], {})


if __name__ == "__main__":
    unittest.main()
