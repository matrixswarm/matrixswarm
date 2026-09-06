"""Native MCP tools for the operator-enabled Phoenix LLM Bridge."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional

from . import __version__
from .bridge_client import call_bridge
from .cli import default_data_dir


BridgeCall = Callable[[Path, str, Optional[dict[str, Any]]], dict[str, Any]]

SERVER_INSTRUCTIONS = (
    "Phoenix is authoritative. These tools work only while a human has unlocked the Phoenix vault and "
    "explicitly enabled LLM Bridge for that Phoenix session. Never ask for, reconstruct, or expose vault "
    "credentials. Start with phoenix_bridge_status, then discover deployments and sessions. Use identifiers "
    "returned by Phoenix. phoenix_launch_deployment always causes a separate human confirmation in Phoenix. "
    "Log subscriptions are temporary and are revoked when the bridge is disabled, the vault closes, or Phoenix exits."
)

MCP_TOOL_NAMES = (
    "phoenix_bridge_status",
    "phoenix_list_deployments",
    "phoenix_list_sessions",
    "phoenix_list_agents",
    "phoenix_agent_tree",
    "phoenix_start_agent_logs",
    "phoenix_read_agent_logs",
    "phoenix_launch_deployment",
)


class PhoenixMcpAdapter:
    """Exact, narrow mapping from MCP tools to the authenticated bridge."""

    def __init__(self, data_dir: Path, bridge_call: BridgeCall = call_bridge):
        self._data_dir = data_dir
        self._bridge_call = bridge_call

    def _call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._bridge_call(self._data_dir, method, params)

    def bridge_status(self) -> dict[str, Any]:
        return self._call("bridge.status")

    def list_deployments(self) -> dict[str, Any]:
        return self._call("deployment.list")

    def list_sessions(self) -> dict[str, Any]:
        return self._call("session.list")

    def list_agents(self, deployment_id: str) -> dict[str, Any]:
        return self._call("agent.list", {"deployment_id": deployment_id})

    def agent_tree(self, session_id: str, refresh: bool = True) -> dict[str, Any]:
        return self._call("agent.tree", {"session_id": session_id, "refresh": refresh})

    def start_agent_logs(self, session_id: str, agent_id: str, follow: bool = True) -> dict[str, Any]:
        return self._call(
            "agent.logs.start",
            {"session_id": session_id, "agent_id": agent_id, "follow": follow},
        )

    def read_agent_logs(self, subscription_id: str, after: int = 0, limit: int = 100) -> dict[str, Any]:
        return self._call(
            "agent.logs.read",
            {"subscription_id": subscription_id, "after": after, "limit": limit},
        )

    def launch_deployment(self, deployment_id: str) -> dict[str, Any]:
        return self._call("deployment.launch", {"deployment_id": deployment_id})


def create_server(
    data_dir: Path | None = None,
    bridge_call: BridgeCall = call_bridge,
) -> Any:
    """Create the SDK server while keeping MCP an optional dependency."""
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations

    adapter = PhoenixMcpAdapter(data_dir or default_data_dir(), bridge_call)
    server = MCPServer(
        name="phoenix-terminal",
        title="Phoenix Terminal",
        description="Operator-gated, redacted access to a running Phoenix Cockpit.",
        instructions=SERVER_INSTRUCTIONS,
        version=__version__,
    )
    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    temporary_write = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
    connection_write = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )

    def expected_bridge_result(operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return operation()
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from None

    @server.tool(
        name="phoenix_bridge_status",
        title="Check Phoenix bridge",
        description=(
            "Check whether the human-enabled Phoenix bridge is reachable and report vault and active-session state. "
            "Call this before other Phoenix tools."
        ),
        annotations=read_only,
    )
    def phoenix_bridge_status() -> dict[str, Any]:
        return expected_bridge_result(adapter.bridge_status)

    @server.tool(
        name="phoenix_list_deployments",
        title="List Phoenix deployments",
        description="List redacted deployment identifiers and labels from the currently unlocked Phoenix vault.",
        annotations=read_only,
    )
    def phoenix_list_deployments() -> dict[str, Any]:
        return expected_bridge_result(adapter.list_deployments)

    @server.tool(
        name="phoenix_list_sessions",
        title="List Phoenix sessions",
        description="List Phoenix deployment sessions and whether each runtime process is running or stopped.",
        annotations=read_only,
    )
    def phoenix_list_sessions() -> dict[str, Any]:
        return expected_bridge_result(adapter.list_sessions)

    @server.tool(
        name="phoenix_list_agents",
        title="List deployment agents",
        description=(
            "List redacted agents for one deployment. deployment_id may be the vault ID or an unambiguous label "
            "returned by phoenix_list_deployments."
        ),
        annotations=read_only,
    )
    def phoenix_list_agents(deployment_id: str) -> dict[str, Any]:
        return expected_bridge_result(lambda: adapter.list_agents(deployment_id))

    @server.tool(
        name="phoenix_agent_tree",
        title="Read live agent tree",
        description=(
            "Read the redacted live agent tree for an active session. session_id may be the runtime session ID, "
            "deployment ID, or unambiguous deployment label. Set refresh false only to use Phoenix's cache."
        ),
        annotations=read_only,
    )
    def phoenix_agent_tree(session_id: str, refresh: bool = True) -> dict[str, Any]:
        return expected_bridge_result(lambda: adapter.agent_tree(session_id, refresh))

    @server.tool(
        name="phoenix_start_agent_logs",
        title="Start redacted agent logs",
        description=(
            "Create a temporary redacted log subscription for one agent in an active Phoenix session. Returns a "
            "subscription_id for phoenix_read_agent_logs. This changes only ephemeral bridge state."
        ),
        annotations=temporary_write,
    )
    def phoenix_start_agent_logs(session_id: str, agent_id: str, follow: bool = True) -> dict[str, Any]:
        return expected_bridge_result(lambda: adapter.start_agent_logs(session_id, agent_id, follow))

    @server.tool(
        name="phoenix_read_agent_logs",
        title="Read redacted agent logs",
        description=(
            "Read buffered redacted lines from a temporary log subscription. Pass next_cursor back as after to read "
            "only newer lines. Phoenix caps limit at 200."
        ),
        annotations=read_only,
    )
    def phoenix_read_agent_logs(subscription_id: str, after: int = 0, limit: int = 100) -> dict[str, Any]:
        return expected_bridge_result(lambda: adapter.read_agent_logs(subscription_id, after, limit))

    @server.tool(
        name="phoenix_launch_deployment",
        title="Request Phoenix deployment connection",
        description=(
            "Ask Phoenix to open one configured deployment session. This never deploys MatrixOS and always presents "
            "a separate Yes/No confirmation in Phoenix before a new connection is opened."
        ),
        annotations=connection_write,
    )
    def phoenix_launch_deployment(deployment_id: str) -> dict[str, Any]:
        return expected_bridge_result(lambda: adapter.launch_deployment(deployment_id))

    return server


def main(data_dir: Path | None = None) -> int:
    try:
        server = create_server(data_dir)
    except ModuleNotFoundError as exc:
        if exc.name == "mcp" or (exc.name and exc.name.startswith("mcp.")):
            print(
                'Phoenix MCP dependencies are not installed. Run: python -m pip install -e ".[mcp]"',
                file=sys.stderr,
            )
            return 2
        raise
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
