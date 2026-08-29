"""Security-focused tests for the hermetic MCP reflex boundary."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "matrixos" / "agents" / "python_core" / "mcp_reflex"
sys.path.insert(0, str(ROOT / "matrixos"))
from core.python_core.mixin.mcp_reflex_policy import (  # noqa: E402
    PolicyError,
    allowed_tools,
    authorize_tool,
    server_config,
)


def policy() -> dict:
    return {
        "servers": {"safe-server": {
            "command": "/opt/mcp/bin/safe-server", "args": ["--stdio"],
            "env": {"SAFE_MODE": "1"}, "allowed_tools": ["status", "echo"],
            "timeout_sec": 12,
        }},
        "access_control": {"callers": {
            "cognitive-agent-1": {"servers": {"safe-server": ["status"]}}
        }},
    }


class McpReflexPolicyTests(unittest.TestCase):
    def test_grants_are_exact_and_intersect_server_allowlist(self) -> None:
        self.assertEqual(allowed_tools(policy(), "cognitive-agent-1", "safe-server"), {"status"})
        self.assertEqual(authorize_tool(policy(), "cognitive-agent-1", "safe-server", "status")["command"], "/opt/mcp/bin/safe-server")

    def test_denies_unlisted_caller_and_tool(self) -> None:
        with self.assertRaises(PolicyError):
            allowed_tools(policy(), "unknown-agent", "safe-server")
        with self.assertRaises(PolicyError):
            authorize_tool(policy(), "cognitive-agent-1", "safe-server", "echo")

    def test_missing_server_allowlist_is_a_deny(self) -> None:
        config = policy()
        del config["servers"]["safe-server"]["allowed_tools"]
        with self.assertRaises(PolicyError):
            allowed_tools(config, "cognitive-agent-1", "safe-server")

    def test_server_command_must_be_absolute(self) -> None:
        config = policy()
        config["servers"]["safe-server"]["command"] = "python"
        with self.assertRaisesRegex(PolicyError, "absolute path"):
            server_config(config, "safe-server")

    def test_validated_server_config_crosses_json_boundary(self) -> None:
        encoded = json.dumps(
            authorize_tool(
                policy(), "cognitive-agent-1", "safe-server", "status"
            )
        )
        self.assertIn('"allowed_tools": ["echo", "status"]', encoded)


class McpReflexBoundaryTests(unittest.TestCase):
    def test_sealed_sources_are_forced_to_lf_on_windows_checkouts(self) -> None:
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn(
            "matrixos/scripts/matrix-mcp-launch text eol=lf", attributes
        )
        self.assertIn(
            "matrixos/agents/python_core/mcp_reflex/*.py text eol=lf",
            attributes,
        )
        self.assertIn(
            "matrixos/agents/python_core/mcp_reflex/worker/*.py text eol=lf",
            attributes,
        )

    def test_matrix_agent_does_not_import_mcp_sdk(self) -> None:
        source = (AGENT_DIR / "mcp_reflex.py").read_text(encoding="utf-8")
        self.assertNotIn("from mcp ", source)
        self.assertIn("identity.has_verified_identity()", source)

    def test_matrix_agent_pins_the_exact_worker_source(self) -> None:
        source = (AGENT_DIR / "mcp_reflex.py").read_text(encoding="utf-8")
        worker = (AGENT_DIR / "worker" / "mcp_stdio_worker.py").read_bytes()
        digest = hashlib.sha256(worker).hexdigest()
        self.assertIn(f'WORKER_SHA256 = "{digest}"', source)

    def test_sdk_worker_does_not_import_matrixswarm(self) -> None:
        source = (AGENT_DIR / "worker" / "mcp_stdio_worker.py").read_text(encoding="utf-8")
        for forbidden in ("matrixos", "BootAgent", "IdentityObject"):
            self.assertNotIn(forbidden, source)

    def test_sdk_is_not_added_to_global_requirements(self) -> None:
        global_requirements = (ROOT / "matrixos" / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("\nmcp", global_requirements.lower())
        worker_requirements = (AGENT_DIR / "worker" / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("mcp>=2,<3", worker_requirements)

    def test_production_meta_requires_root_owned_sandbox_launcher(self) -> None:
        metadata = json.loads(
            (ROOT / "phoenix" / "agents_meta" / "mcp_reflex.json").read_text(
                encoding="utf-8"
            )
        )
        sandbox = metadata["config"]["sandbox"]
        self.assertTrue(sandbox["enabled"])
        self.assertEqual(
            sandbox["launcher"], "/usr/local/libexec/matrix-mcp-launch"
        )
        self.assertEqual(sandbox["worker_account"], "railgun-managed")

    def test_privilege_drop_launcher_accepts_no_command_arguments(self) -> None:
        launcher = (
            ROOT / "matrixos" / "scripts" / "matrix-mcp-launch"
        ).read_text(encoding="utf-8")
        self.assertIn("if len(sys.argv) != 1", launcher)
        self.assertIn('os.environ.get("SUDO_USER"', launcher)
        self.assertIn("os.setgroups([])", launcher)
        self.assertIn("os.setgid(account.pw_gid)", launcher)
        self.assertIn("os.setuid(account.pw_uid)", launcher)
        self.assertIn("PR_SET_NO_NEW_PRIVS", launcher)
        self.assertIn("RLIMIT_FSIZE", launcher)
        self.assertNotIn("subprocess", launcher)
        self.assertIn("preserve_lexical_path=True", launcher)
        self.assertIn(
            "return lexical if preserve_lexical_path else resolved", launcher
        )

    def test_parent_bounds_worker_output_and_rejects_replay(self) -> None:
        source = (AGENT_DIR / "mcp_reflex.py").read_text(encoding="utf-8")
        self.assertIn("tempfile.TemporaryFile", source)
        self.assertNotIn("stdout=subprocess.PIPE", source)
        self.assertIn("worker request exceeds configured limit", source)
        self.assertIn("request_id was already completed", source)

    def test_worker_health_protocol(self) -> None:
        worker = AGENT_DIR / "worker" / "mcp_stdio_worker.py"
        completed = subprocess.run([sys.executable, str(worker)], input=b'{"operation":"health"}\n', stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        response = json.loads(completed.stdout)
        self.assertTrue(response["ok"])
        self.assertIn("sdk_available", response["result"])

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "isolated MCP SDK is not installed")
    def test_mcp_v2_stdio_discovery_filter_and_call(self) -> None:
        worker = AGENT_DIR / "worker" / "mcp_stdio_worker.py"
        server = ROOT / "tests" / "fixtures" / "mcp_echo_server.py"
        base_request = {
            "server": {
                "command": sys.executable,
                "args": [str(server)],
                "env": {},
                "timeout_sec": 15,
                "allowed_tools": ["echo", "hidden"],
            },
            "permitted_tools": ["echo"],
        }

        listed = subprocess.run(
            [sys.executable, str(worker)],
            input=(json.dumps({"operation": "list_tools", **base_request}) + "\n").encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )
        self.assertEqual(listed.returncode, 0, listed.stderr.decode())
        list_response = json.loads(listed.stdout)
        self.assertTrue(list_response["ok"], list_response)
        self.assertEqual(
            [tool["name"] for tool in list_response["result"]["tools"]],
            ["echo"],
        )

        called = subprocess.run(
            [sys.executable, str(worker)],
            input=(json.dumps({
                "operation": "call_tool",
                "tool_name": "echo",
                "arguments": {"message": "sealed"},
                **base_request,
            }) + "\n").encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )
        self.assertEqual(called.returncode, 0, called.stderr.decode())
        call_response = json.loads(called.stdout)
        self.assertTrue(call_response["ok"], call_response)
        self.assertEqual(
            call_response["result"]["structuredContent"],
            {"message": "sealed"},
        )

        denied = subprocess.run(
            [sys.executable, str(worker)],
            input=(json.dumps({
                "operation": "call_tool",
                "tool_name": "hidden",
                "arguments": {},
                **base_request,
            }) + "\n").encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )
        self.assertEqual(denied.returncode, 0, denied.stderr.decode())
        denied_response = json.loads(denied.stdout)
        self.assertFalse(denied_response["ok"], denied_response)
        self.assertIn("tool is not permitted", denied_response["error"])

if __name__ == "__main__":
    unittest.main()
