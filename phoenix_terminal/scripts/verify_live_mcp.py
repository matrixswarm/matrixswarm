"""Exercise the native MCP adapter against an operator-enabled Phoenix bridge."""

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


async def verify(exercise_logs: bool, launch_deployment: str | None) -> dict[str, Any]:
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
        tool_names = {tool.name for tool in listed.tools}
        expected = set(MCP_TOOL_NAMES)
        if tool_names != expected:
            raise RuntimeError(
                f"MCP tool surface mismatch: missing={sorted(expected - tool_names)}, "
                f"unexpected={sorted(tool_names - expected)}"
            )
        summary["tools"] = sorted(tool_names)

        status = await _call(client, "phoenix_bridge_status", {})
        if status.get("bridge") != "ready" or status.get("vault") != "unlocked":
            raise RuntimeError(f"Phoenix is not ready for acceptance: {status}")
        summary["bridge"] = status.get("bridge")
        summary["vault"] = status.get("vault")

        deployments_result = await _call(client, "phoenix_list_deployments", {})
        sessions_result = await _call(client, "phoenix_list_sessions", {})
        deployments = deployments_result.get("deployments") or []
        sessions = sessions_result.get("sessions") or []
        summary["deployment_count"] = len(deployments)
        summary["session_count"] = len(sessions)

        if deployments:
            deployment_id = str(deployments[0]["id"])
            agents_result = await _call(
                client,
                "phoenix_list_agents",
                {"deployment_id": deployment_id},
            )
            summary["agent_count"] = len(agents_result.get("agents") or [])

        if sessions:
            session_id = str(sessions[0]["session_id"])
            tree = await _call(
                client,
                "phoenix_agent_tree",
                {"session_id": session_id, "refresh": True},
            )
            summary["tree_state"] = tree.get("state")
            summary["tree_agent_count"] = len(tree.get("agents") or [])

            if exercise_logs:
                agents = agents_result.get("agents") if deployments else []
                if not agents:
                    raise RuntimeError("no deployment agent is available for log acceptance")
                agent_id = str(agents[0]["universal_id"])
                started = await _call(
                    client,
                    "phoenix_start_agent_logs",
                    {"session_id": session_id, "agent_id": agent_id, "follow": False},
                )
                subscription_id = str(started["subscription_id"])
                await asyncio.sleep(1)
                logs = await _call(
                    client,
                    "phoenix_read_agent_logs",
                    {"subscription_id": subscription_id, "after": 0, "limit": 20},
                )
                summary["logs_state"] = logs.get("state")
                summary["log_line_count"] = len(logs.get("lines") or [])

        if launch_deployment:
            launched = await _call(
                client,
                "phoenix_launch_deployment",
                {"deployment_id": launch_deployment},
            )
            summary["launch_state"] = launched.get("state")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--exercise-logs",
        action="store_true",
        help="Create and read one temporary, redacted log subscription.",
    )
    parser.add_argument(
        "--launch-deployment",
        metavar="ID",
        help="Request one Phoenix-confirmed connection for the supplied deployment ID.",
    )
    args = parser.parse_args()
    try:
        summary = asyncio.run(verify(args.exercise_logs, args.launch_deployment))
    # The MCP client's task group may wrap a tool failure in ExceptionGroup on
    # Python 3.11+, so keep the command-line failure compact at this boundary.
    except Exception as exc:
        print(f"Live MCP acceptance failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
