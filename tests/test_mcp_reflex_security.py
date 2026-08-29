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
from core.python_core.mixin.mcp_reflex_client import (  # noqa: E402
    McpReflexClientError,
    McpReflexClientMixin,
)
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import (  # noqa: E402
    IdentityObject,
)

EDITOR_DIR = (
    ROOT
    / "phoenix"
    / "matrix_gui"
    / "swarm_workspace"
    / "cls_lib"
    / "agent"
    / "config_editors"
)
_editor_model_spec = importlib.util.spec_from_file_location(
    "mcp_reflex_editor_model", EDITOR_DIR / "mcp_reflex_model.py"
)
assert _editor_model_spec and _editor_model_spec.loader
_editor_model = importlib.util.module_from_spec(_editor_model_spec)
_editor_model_spec.loader.exec_module(_editor_model)


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
        self.assertIn(
            "matrixos/agents/python_core/mcp_reflex_probe/*.py text eol=lf",
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

    def test_airlock_handler_diagnostics_are_bounded_and_payload_free(self) -> None:
        source = (AGENT_DIR / "mcp_reflex.py").read_text(encoding="utf-8")
        self.assertIn("[MCP-AIRLOCK][HANDLER-ENTER]", source)
        self.assertIn("[MCP-AIRLOCK][HANDLER-EXIT]", source)
        self.assertIn("identity_type_match=", source)
        self.assertIn("uid_present=", source)
        handler_region = source[source.index("def _dispatch_request"):source.index("def _handle_request")]
        for secret_field in ('content=', 'arguments=', 'server_env=', 'result='):
            self.assertNotIn(secret_field, handler_region)

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

    def test_phoenix_has_structured_airlock_and_probe_editors(self) -> None:
        reflex_editor = (EDITOR_DIR / "mcp_reflex.py").read_text(encoding="utf-8")
        probe_editor = (EDITOR_DIR / "mcp_reflex_probe.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("class McpReflex(BaseEditor)", reflex_editor)
        self.assertIn("class McpServerDialog", reflex_editor)
        self.assertIn("class McpGrantDialog", reflex_editor)
        self.assertIn('"require_verified_identity": True', reflex_editor)
        self.assertIn("class McpReflexProbe(BaseEditor)", probe_editor)
        self.assertIn("self.run_on_boot.isChecked()", probe_editor)

    def test_phoenix_editor_builds_exact_default_deny_policy(self) -> None:
        servers = {
            "smoke": {
                "command": "/matrix/mcp/.venv/bin/python3",
                "args": ["/opt/matrixswarm/mcp-smoke/echo_server.py"],
                "env": {},
                "allowed_tools": ["hidden", "echo", "echo"],
                "timeout_sec": 15,
            }
        }
        grants = [{
            "caller_uid": "mcp-reflex-probe-f90b85",
            "server_id": "smoke",
            "tools": ["echo"],
        }]
        safe_servers, access = _editor_model.validated_policy(servers, grants)
        self.assertEqual(safe_servers["smoke"]["allowed_tools"], ["echo", "hidden"])
        self.assertEqual(access["default"], "deny")
        self.assertEqual(
            access["callers"]["mcp-reflex-probe-f90b85"]["servers"]["smoke"],
            ["echo"],
        )

    def test_phoenix_editor_rejects_relative_commands_and_overbroad_grants(self) -> None:
        server = {
            "smoke": {
                "command": "python3",
                "args": [],
                "env": {},
                "allowed_tools": ["echo"],
                "timeout_sec": 15,
            }
        }
        with self.assertRaisesRegex(_editor_model.McpReflexConfigError, "absolute"):
            _editor_model.validate_servers(server)
        server["smoke"]["command"] = "/usr/bin/python3"
        with self.assertRaisesRegex(
            _editor_model.McpReflexConfigError, "outside.*allowlist"
        ):
            _editor_model.build_access_control(
                [{
                    "caller_uid": "probe-1",
                    "server_id": "smoke",
                    "tools": ["hidden"],
                }],
                server,
            )

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


class _FakeEndpoint:
    def __init__(self, uid: str, handler: str) -> None:
        self.uid = uid
        self.handler = handler

    def get_universal_id(self) -> str:
        return self.uid

    def get_handler(self) -> str:
        return self.handler


class _FakePacket:
    def set_data(self, data: dict) -> None:
        self.data = data

    def set_packet(self, packet: "_FakePacket", field_name: str = "content") -> None:
        self.data[field_name] = packet.data

    def set_auto_fill_sub_packet(self, enabled: bool = True) -> "_FakePacket":
        self.auto_fill_sub_packet = enabled
        return self


class _FakeMcpClient(McpReflexClientMixin):
    def __init__(self) -> None:
        self.endpoint = _FakeEndpoint("mcp-reflex-1", "cmd_mcp_call_tool")
        self.roles: list[str] = []
        self.deliveries: list[tuple[_FakePacket, str]] = []
        self.results: list[tuple[dict, dict]] = []
        self.delivery_result = True
        self.extra_endpoint = False
        self.logs: list[tuple[str, str]] = []
        self.init_mcp_reflex_client(max_pending=2, request_timeout_sec=60)

    def get_nodes_by_role(self, role: str):
        self.roles.append(role)
        self.endpoint.handler = (
            "cmd_mcp_list_tools"
            if role == "hive.mcp.tools"
            else "cmd_mcp_call_tool"
        )
        endpoints = [self.endpoint]
        if self.extra_endpoint:
            endpoints.append(_FakeEndpoint("mcp-reflex-2", self.endpoint.handler))
        return endpoints

    def get_delivery_packet(self, packet_type: str) -> _FakePacket:
        if packet_type not in {
            "standard.command.packet", "standard.general.json.packet"
        }:
            raise AssertionError(packet_type)
        return _FakePacket()

    def pass_packet(self, packet: _FakePacket, target_uid: str) -> bool:
        self.deliveries.append((packet, target_uid))
        return self.delivery_result

    def on_mcp_result(self, content: dict, pending: dict) -> None:
        self.results.append((content, pending))

    def log(self, message: str, level: str = "INFO") -> None:
        self.logs.append((message, level))


class McpReflexClientTests(unittest.TestCase):
    def test_signed_client_routes_directly_and_rejects_forged_callback(self):
        client = _FakeMcpClient()
        request_id = client.request_mcp_tool_call(
            "smoke",
            "echo",
            {"message": "Airlock is tight"},
            request_id="probe-1",
            context={"phase": "echo"},
        )
        self.assertEqual(request_id, "probe-1")
        self.assertEqual(client.roles, ["hive.mcp.call_tool"])
        packet, target_uid = client.deliveries[0]
        self.assertEqual(target_uid, "mcp-reflex-1")
        self.assertEqual(packet.data["handler"], "cmd_mcp_call_tool")
        self.assertEqual(packet.data["content"]["tool_name"], "echo")
        self.assertFalse(packet.auto_fill_sub_packet)
        self.assertNotIn("cmd_service_request", repr(packet.data))
        self.assertTrue(any("request delivered" in item[0] for item in client.logs))

        reply = {
            "request_id": "probe-1",
            "operation": "call_tool",
            "status": "ok",
            "result": {"structuredContent": {"message": "Airlock is tight"}},
        }
        client.cmd_mcp_result(
            reply, None, IdentityObject(True, "forged-reflex")
        )
        self.assertEqual(client.results, [])
        self.assertIn("probe-1", client._mcp_client_pending)

        client.cmd_mcp_result(
            reply, None, IdentityObject(True, "mcp-reflex-1")
        )
        self.assertEqual(len(client.results), 1)
        self.assertEqual(
            client.results[0][1]["context"], {"phase": "echo"}
        )
        self.assertNotIn("probe-1", client._mcp_client_pending)
        self.assertTrue(
            any("verified callback accepted" in item[0] for item in client.logs)
        )

    def test_client_audits_rejected_callback_without_releasing_request(self):
        client = _FakeMcpClient()
        client.request_mcp_tools("smoke", request_id="audit-1")
        client.cmd_mcp_result(
            {"request_id": "audit-1", "operation": "list_tools"},
            None,
            IdentityObject(False, "mcp-reflex-1"),
        )
        self.assertIn("audit-1", client._mcp_client_pending)
        self.assertTrue(
            any("unverified identity" in item[0] for item in client.logs)
        )

    def test_client_rejects_duplicate_request_ids(self):
        client = _FakeMcpClient()
        client.request_mcp_tools("smoke", request_id="same-id")
        with self.assertRaisesRegex(McpReflexClientError, "already pending"):
            client.request_mcp_tools("smoke", request_id="same-id")

    def test_failed_delivery_releases_pending_capacity(self):
        client = _FakeMcpClient()
        client.delivery_result = False
        with self.assertRaisesRegex(McpReflexClientError, "delivery failed"):
            client.request_mcp_tools("smoke", request_id="not-delivered")
        self.assertEqual(client._mcp_client_pending, {})

    def test_ambiguous_airlock_endpoints_fail_closed(self):
        client = _FakeMcpClient()
        client.extra_endpoint = True
        with self.assertRaisesRegex(McpReflexClientError, "exactly one"):
            client.request_mcp_tools("smoke")
        self.assertEqual(client.deliveries, [])

    def test_probe_is_opt_in_and_exercises_allow_and_deny(self):
        metadata = json.loads(
            (
                ROOT / "phoenix" / "agents_meta" / "mcp_reflex_probe.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIs(metadata["config"]["run_on_boot"], False)
        probe = (
            ROOT
            / "matrixos"
            / "agents"
            / "python_core"
            / "mcp_reflex_probe"
            / "mcp_reflex_probe.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"echo"', probe)
        self.assertIn('"hidden"', probe)
        self.assertIn("[MCP-PROBE] ✅ PASS", probe)

if __name__ == "__main__":
    unittest.main()
