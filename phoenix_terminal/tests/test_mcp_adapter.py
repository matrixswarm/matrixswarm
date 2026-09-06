from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from phoenix_terminal.bridge.server import BridgeServer
from phoenix_terminal.mcp_server import MCP_TOOL_NAMES, SERVER_INSTRUCTIONS, PhoenixMcpAdapter, create_server


class McpAdapterTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def bridge_call(data_dir, method, params=None):
            self.calls.append((data_dir, method, params))
            return {"method": method, "params": params or {}}

        self.data_dir = Path("test-state")
        self.adapter = PhoenixMcpAdapter(self.data_dir, bridge_call)

    def test_exact_tool_surface_has_no_generic_or_vault_access(self):
        self.assertEqual(
            MCP_TOOL_NAMES,
            (
                "phoenix_bridge_status",
                "phoenix_list_deployments",
                "phoenix_list_sessions",
                "phoenix_list_agents",
                "phoenix_agent_tree",
                "phoenix_start_agent_logs",
                "phoenix_read_agent_logs",
                "phoenix_launch_deployment",
            ),
        )
        self.assertNotIn("call", MCP_TOOL_NAMES)
        self.assertFalse(any("vault" in name for name in MCP_TOOL_NAMES))
        self.assertTrue(SERVER_INSTRUCTIONS.startswith("Phoenix is authoritative."))
        self.assertIn("human", SERVER_INSTRUCTIONS)
        self.assertIn("Never ask for", SERVER_INSTRUCTIONS)
        source = Path(create_server.__code__.co_filename).read_text(encoding="utf-8")
        for forbidden in ("import subprocess", "os.system", "shell=True", "eval(", "exec("):
            self.assertNotIn(forbidden, source)

    def test_adapter_maps_only_allowlisted_bridge_methods(self):
        self.adapter.bridge_status()
        self.adapter.list_deployments()
        self.adapter.list_sessions()
        self.adapter.list_agents("demo")
        self.adapter.agent_tree("runtime-1", False)
        self.adapter.start_agent_logs("runtime-1", "matrix", True)
        self.adapter.read_agent_logs("sub-1", 12, 50)
        self.adapter.launch_deployment("demo")
        self.assertEqual(
            [method for _data_dir, method, _params in self.calls],
            [
                "bridge.status",
                "deployment.list",
                "session.list",
                "agent.list",
                "agent.tree",
                "agent.logs.start",
                "agent.logs.read",
                "deployment.launch",
            ],
        )
        self.assertTrue(all(data_dir == self.data_dir for data_dir, _method, _params in self.calls))
        self.assertEqual(self.calls[-1][2], {"deployment_id": "demo"})

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "MCP SDK is not installed")
    def test_sdk_discovery_exposes_hints_and_structured_results(self):
        import asyncio

        from mcp import Client

        async def exercise():
            server = create_server(self.data_dir, self.adapter._bridge_call)
            async with Client(server) as client:
                self.assertEqual(client.instructions, SERVER_INSTRUCTIONS)
                listed = await client.list_tools()
                tools = {tool.name: tool for tool in listed.tools}
                self.assertEqual(set(tools), set(MCP_TOOL_NAMES))
                for name in MCP_TOOL_NAMES:
                    self.assertTrue(tools[name].description)
                self.assertTrue(tools["phoenix_bridge_status"].annotations.read_only_hint)
                self.assertFalse(tools["phoenix_start_agent_logs"].annotations.read_only_hint)
                self.assertFalse(tools["phoenix_launch_deployment"].annotations.read_only_hint)
                self.assertFalse(tools["phoenix_launch_deployment"].annotations.destructive_hint)
                result = await client.call_tool("phoenix_bridge_status", {})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["method"], "bridge.status")

            def disabled_bridge(_data_dir, _method, _params=None):
                raise RuntimeError("Phoenix bridge is not running")

            disabled_server = create_server(self.data_dir, disabled_bridge)
            async with Client(disabled_server) as client:
                result = await client.call_tool("phoenix_bridge_status", {})
                self.assertTrue(result.is_error)
                self.assertIn("Phoenix bridge is not running", result.content[0].text)

        asyncio.run(exercise())

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "MCP SDK is not installed")
    def test_stdio_subprocess_reaches_authenticated_bridge(self):
        import asyncio

        from mcp import Client, StdioServerParameters

        calls = []

        def dispatch(method, params):
            calls.append((method, params))
            return {"method": method, "params": params}

        async def exercise(data_dir):
            environment = dict(os.environ)
            environment["PHOENIX_TERMINAL_DATA_DIR"] = str(data_dir)
            process = StdioServerParameters(
                command=sys.executable,
                args=["-m", "phoenix_terminal.mcp_server"],
                env=environment,
                cwd=str(Path(__file__).resolve().parents[1]),
            )
            async with Client(process) as client:
                listed = await client.list_tools()
                self.assertEqual({tool.name for tool in listed.tools}, set(MCP_TOOL_NAMES))
                result = await client.call_tool("phoenix_bridge_status", {})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["method"], "bridge.status")

        with TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory)
            bridge = BridgeServer(dispatch, data_dir)
            bridge.start()
            try:
                asyncio.run(exercise(data_dir))
            finally:
                bridge.stop()
        self.assertEqual(calls, [("bridge.status", {})])


if __name__ == "__main__":
    unittest.main()
