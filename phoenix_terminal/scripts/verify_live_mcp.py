"""Exercise read-only MCP against an operator-enabled headless test inventory."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

from phoenix_terminal.mcp_server import MCP_TOOL_NAMES


FORBIDDEN_KEY_PARTS = (
    "password",
    "private_key",
    "secret",
    "swarm_key",
    "token",
    "vault_data",
)


def _assert_redacted(value: Any, path: str = "result") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(part in normalized for part in FORBIDDEN_KEY_PARTS):
                raise RuntimeError(f"sensitive field crossed the MCP boundary: {path}.{key}")
            _assert_redacted(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_redacted(child, f"{path}[{index}]")
    elif isinstance(value, str) and "-----BEGIN PRIVATE KEY-----" in value:
        raise RuntimeError(f"private-key material crossed the MCP boundary: {path}")


async def _call(client: Client, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await client.call_tool(name, arguments)
    if result.is_error:
        detail = result.content[0].text if result.content else "unknown MCP error"
        raise RuntimeError(f"{name} failed: {detail}")
    structured = result.structured_content
    if not isinstance(structured, dict):
        raise RuntimeError(f"{name} returned no structured object")
    _assert_redacted(structured, name)
    return structured


async def verify() -> dict[str, Any]:
    """Read only an already-enabled test assignment. Never connect or launch."""
    terminal_root = Path(__file__).resolve().parents[1]
    process = StdioServerParameters(
        command=sys.executable,
        args=["-m", "phoenix_terminal.mcp_server"],
        env=dict(os.environ),
        cwd=str(terminal_root),
    )
    summary: dict[str, Any] = {}
    async with Client(process) as client:
        listed = await client.list_tools()
        names = {tool.name for tool in listed.tools}
        if names != set(MCP_TOOL_NAMES):
            raise RuntimeError("MCP tool surface does not match the five read-only inventory tools.")
        if not all(tool.annotations and tool.annotations.read_only_hint for tool in listed.tools):
            raise RuntimeError("Every published inventory tool must be read-only.")
        summary["tools"] = sorted(names)
        status = await _call(client, "phoenix_bridge_status", {})
        if status.get("mode") != "headless_inventory" or status.get("read_only") is not True:
            raise RuntimeError("Expected an operator-enabled headless inventory endpoint.")
        summary["mode"] = status["mode"]
        described = await _call(client, "phoenix_describe_tools", {})
        if described.get("remote_actions_available") is not False:
            raise RuntimeError("Inventory endpoint must not expose remote actions.")
        deployments = (await _call(client, "phoenix_list_deployments", {})).get("deployments", [])
        summary["deployment_count"] = len(deployments)
        if deployments:
            deployment_id = deployments[0]["id"]
            agents = (await _call(client, "phoenix_list_agents",
                                 {"deployment_id": deployment_id})).get("agents", [])
            summary["agent_count"] = len(agents)
            if agents:
                await _call(client, "phoenix_describe_agent",
                            {"deployment_id": deployment_id, "agent_id": agents[0]["universal_id"]})
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        summary = asyncio.run(verify())
    # The MCP client's task group may wrap a tool failure in ExceptionGroup on
    # Python 3.11+, so keep the command-line failure compact at this boundary.
    except Exception as exc:
        print(f"Live MCP acceptance failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
