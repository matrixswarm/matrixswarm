"""Tests for the reusable authenticated encrypted agent-state store."""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
from core.python_core.mixin.encrypted_state import (  # noqa: E402
    EncryptedStateError,
    EncryptedStateMixin,
)


class _StateAgent(EncryptedStateMixin):
    def __init__(self, root: str) -> None:
        self.command_line_args = {"universal_id": "cognitive-agent-1"}
        self.tree_node = {
            "config": {
                "security": {
                    "symmetric_encryption": {
                        "type": "aes",
                        "key": base64.b64encode(b"x" * 32).decode("ascii"),
                    }
                }
            }
        }
        self.path_resolution = {"static_comm_path_resolved": root}


class EncryptedStateMixinTests(unittest.TestCase):
    def test_round_trip_is_encrypted_and_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = _StateAgent(directory)
            agent.init_encrypted_state(namespace="cognitive")
            agent.save_encrypted_state("checkpoint", {"response_id": "r-1"})
            self.assertEqual(
                agent.load_encrypted_state("checkpoint"),
                {"response_id": "r-1"},
            )
            path = Path(directory, "cognitive", "checkpoint.json.aes")
            on_disk = path.read_text()
            self.assertNotIn("response_id", on_disk)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertTrue(agent.delete_encrypted_state("checkpoint"))
            self.assertIsNone(agent.load_encrypted_state("checkpoint"))

    def test_nested_run_state_survives_agent_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = _StateAgent(directory)
            first.init_encrypted_state(namespace="cognitive")
            first.save_encrypted_state(
                "checkpoint",
                {
                    "run_id": "run-123",
                    "response_id": "resp-456",
                    "tool_call_ids": ["call-1", "call-2"],
                    "budget": {"turns_remaining": 8},
                },
                directory="runs/run-123",
            )

            restarted = _StateAgent(directory)
            restarted.init_encrypted_state(namespace="cognitive")
            self.assertEqual(
                restarted.load_encrypted_state(
                    "checkpoint", directory="runs/run-123"
                )["response_id"],
                "resp-456",
            )
            encrypted = Path(
                directory,
                "cognitive",
                "runs",
                "run-123",
                "checkpoint.json.aes",
            ).read_text()
            self.assertNotIn("resp-456", encrypted)

    def test_nested_directory_cannot_escape_agent_static_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = _StateAgent(directory)
            agent.init_encrypted_state(namespace="cognitive")
            for unsafe in ("../outside", "/absolute", "runs//broken", "runs\\outside"):
                with self.subTest(directory=unsafe):
                    with self.assertRaises(EncryptedStateError):
                        agent.save_encrypted_state(
                            "checkpoint", {"ok": False}, directory=unsafe
                        )

    def test_state_is_bound_to_agent_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = _StateAgent(directory)
            first.init_encrypted_state(namespace="cognitive")
            first.save_encrypted_state("checkpoint", {"ok": True})
            second = _StateAgent(directory)
            second.command_line_args["universal_id"] = "another-agent"
            second.init_encrypted_state(namespace="cognitive")
            with self.assertRaises(EncryptedStateError):
                second.load_encrypted_state("checkpoint")

    def test_missing_phoenix_symmetric_key_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = _StateAgent(directory)
            agent.tree_node = {"config": {}}
            with self.assertRaises(EncryptedStateError):
                agent.init_encrypted_state(namespace="cognitive")

    def test_ciphertext_and_path_are_authenticated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            agent = _StateAgent(directory)
            agent.init_encrypted_state(namespace="cognitive")
            agent.save_encrypted_state(
                "checkpoint", {"approved": True}, directory="runs/run-a"
            )
            source = Path(
                directory, "cognitive", "runs", "run-a", "checkpoint.json.aes"
            )
            envelope = json.loads(source.read_text())

            moved = Path(
                directory, "cognitive", "runs", "run-b", "checkpoint.json.aes"
            )
            moved.parent.mkdir(parents=True)
            moved.write_text(json.dumps(envelope))
            with self.assertRaises(EncryptedStateError):
                agent.load_encrypted_state("checkpoint", directory="runs/run-b")

            ciphertext = bytearray(base64.b64decode(envelope["ciphertext"]))
            ciphertext[-1] ^= 1
            envelope["ciphertext"] = base64.b64encode(ciphertext).decode("ascii")
            source.write_text(json.dumps(envelope))
            with self.assertRaises(EncryptedStateError):
                agent.load_encrypted_state("checkpoint", directory="runs/run-a")


if __name__ == "__main__":
    unittest.main()
