"""Optional MCP adapter for the headless terminal's read-only inventory."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any, Callable, Optional

from .bridge_client import call_bridge
from .cli import default_data_dir

try:
    __version__ = package_version("phoenix-terminal")
except PackageNotFoundError:
    __version__ = "0.2.0"

BridgeCall = Callable[[Path, str, Optional[dict[str, Any]]], dict[str, Any]]
SERVER_INSTRUCTIONS = (
    "The headless operator console owns terminal access; the Phoenix GUI only authors vault records. "
    "These tools require a human to open a vault privately, select inventory, and enable a bounded session. "
    "Never ask for, reconstruct, or expose vault credentials. Start with phoenix_bridge_status and "
    "phoenix_describe_tools. Use exact returned IDs, not labels. Inventory is saved data, not live health. "
    "Terminal Mode is an operator setup window, never permission to act. No remote actions, GUI approvals, "
    "logs, connections, or writes are available. Lock or expiry revokes access."
)
MCP_TOOL_NAMES = (
    "phoenix_bridge_status",
    "phoenix_describe_tools",
    "phoenix_list_deployments",
    "phoenix_list_agents",
    "phoenix_describe_agent",
)


class PhoenixMcpAdapter:
    """Exact, read-only mapping; no generic RPC or credential access."""

    def __init__(self, data_dir: Path, bridge_call: BridgeCall = call_bridge):
        self._data_dir = data_dir
        self._bridge_call = bridge_call

    def _call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._bridge_call(self._data_dir, method, params)

    def bridge_status(self) -> dict[str, Any]:
        return self._call("bridge.status")

    def describe_tools(self) -> dict[str, Any]:
        return self._call("tools.describe")

    def list_deployments(self) -> dict[str, Any]:
        return self._call("deployment.list")

    def list_agents(self, deployment_id: str) -> dict[str, Any]:
        return self._call("agent.list", {"deployment_id": deployment_id})

    def describe_agent(self, deployment_id: str, agent_id: str) -> dict[str, Any]:
        return self._call("agent.describe", {"deployment_id": deployment_id, "agent_id": agent_id})


def create_server(data_dir: Path | None = None, bridge_call: BridgeCall = call_bridge) -> Any:
    """Keep the MCP SDK optional; the ordinary CLI does not require it."""
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations

    adapter = PhoenixMcpAdapter(data_dir or default_data_dir(), bridge_call)
    server = MCPServer(name="phoenix-terminal", title="Phoenix Terminal",
                       description="Operator-selected saved inventory; no GUI bridge or remote execution.",
                       instructions=SERVER_INSTRUCTIONS, version=__version__)
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                idempotentHint=True, openWorldHint=False)

    def result(operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return operation()
        except (RuntimeError, ValueError) as exc:
            raise ToolError(str(exc)) from None

    @server.tool(name="phoenix_bridge_status", title="Check terminal access",
                 description="Read the headless assignment's availability, mode and remaining lifetime.",
                 annotations=read_only)
    def phoenix_bridge_status() -> dict[str, Any]:
        return result(adapter.bridge_status)

    @server.tool(name="phoenix_describe_tools", title="Describe terminal operations",
                 description="Read exact operation schemas and current limitations. No operation is enabled by this call.",
                 annotations=read_only)
    def phoenix_describe_tools() -> dict[str, Any]:
        return result(adapter.describe_tools)

    @server.tool(name="phoenix_list_deployments", title="List selected saved deployments",
                 description="Read only deployment IDs and public labels selected by the operator; not live server state.",
                 annotations=read_only)
    def phoenix_list_deployments() -> dict[str, Any]:
        return result(adapter.list_deployments)

    @server.tool(name="phoenix_list_agents", title="List saved agent inventory",
                 description="Read public inventory for an exact selected deployment ID. Labels and aliases are not accepted.",
                 annotations=read_only)
    def phoenix_list_agents(deployment_id: str) -> dict[str, Any]:
        return result(lambda: adapter.list_agents(deployment_id))

    @server.tool(name="phoenix_describe_agent", title="Describe a saved agent",
                 description="Read public identity for exact selected deployment and agent IDs; no settings or credentials.",
                 annotations=read_only)
    def phoenix_describe_agent(deployment_id: str, agent_id: str) -> dict[str, Any]:
        return result(lambda: adapter.describe_agent(deployment_id, agent_id))

    return server

TERMINAL_TOOL_NAMES = (
    "phoenix_terminal_request", "phoenix_terminal_status", "phoenix_terminal_disconnect",
    "phoenix_terminal_alerts", "phoenix_terminal_swarms",
    "phoenix_terminal_railgun_launch", "phoenix_terminal_railgun_status",
)


class TerminalMcpAdapter:
    """Shares the CLI's opaque client identity and exact approval authorizer."""
    def __init__(self, data_dir, *, identity=None):
        from .terminal_client import TerminalClientIdentity
        self.identity = identity or TerminalClientIdentity(data_dir)
        self.data_dir = data_dir

    def request(self, client_label):
        return self.identity.request(client_label)

    def status(self):
        from .terminal_client import call_terminal
        return self.identity.status() if self.identity.path.is_file() else call_terminal(self.data_dir, "terminal.status", {})

    def disconnect(self):
        return self.identity.disconnect()

    def alerts(self, deployment_id, after=0, limit=100, stream_id=None):
        return self.identity.read_alerts(deployment_id, after=after, limit=limit, stream_id=stream_id)

    def swarms(self, deployment_id):
        return self.identity.list_swarms(deployment_id)

    def launch(self, deployment_id, operation_id):
        return self.identity.launch_railgun(deployment_id, operation_id)

    def launch_status(self, deployment_id, operation_id):
        return self.identity.railgun_status(deployment_id, operation_id)


def create_terminal_server(data_dir=None):
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations
    adapter = TerminalMcpAdapter(data_dir or default_data_dir())
    server = MCPServer(name="phoenix-terminal-access", title="Phoenix Terminal access",
        instructions="A human privately opens the prepared Vault and approves your connection in Phoenix Terminal. "
        "Request access, then check status for effective per-deployment scopes; tool availability is not permission. "
        "Never request credentials or alter policy. Railgun starts only the exact saved deployment on its fixed SSH server; "
        "active universes are refused. Generate and retain one 32-character hex operation ID per intentional launch. "
        "Retries MUST reuse that ID; outcome_unknown requires operator reconciliation, NOT a new launch. "
        "Completion is a request receipt, not proof of live health. Lock, expiry or disconnect revokes access.",
        version=__version__)
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    action = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    def result(callback):
        try:
            return callback()
        except (RuntimeError, ValueError, PermissionError) as exc:
            raise ToolError(str(exc)) from None

    @server.tool(name=TERMINAL_TOOL_NAMES[0], description="Request access; this cannot approve it. Client label is unverified.", annotations=action)
    def request(client_label: str) -> dict[str, Any]:
        return result(lambda: adapter.request(client_label))

    @server.tool(name=TERMINAL_TOOL_NAMES[1], description="Read approval state and exact effective resources/operation names.", annotations=read)
    def status() -> dict[str, Any]:
        return result(adapter.status)

    @server.tool(name=TERMINAL_TOOL_NAMES[2], description="Revoke your connection; other clients are unaffected.", annotations=action)
    def disconnect() -> dict[str, Any]:
        return result(adapter.disconnect)

    @server.tool(name=TERMINAL_TOOL_NAMES[3], description="Read the scoped live-only alert buffer. Pagination after zero requires the returned stream ID.", annotations=read)
    def alerts(deployment_id: str, after: int = 0, limit: int = 100, stream_id: str | None = None) -> dict[str, Any]:
        return result(lambda: adapter.alerts(deployment_id, after, limit, stream_id))

    @server.tool(name=TERMINAL_TOOL_NAMES[4], description="One active-universe inventory on this permitted deployment's fixed saved server. Observing another swarm grants no authority to it.", annotations=read)
    def swarms(deployment_id: str) -> dict[str, Any]:
        return result(lambda: adapter.swarms(deployment_id))

    @server.tool(name=TERMINAL_TOOL_NAMES[5], description="Queue an inactive-only saved deployment launch. Explicit operation_id is 32 lowercase hex characters; ALWAYS reuse it for retries. No alternate targets/options, restarts or replacement.", annotations=action)
    def launch(deployment_id: str, operation_id: str) -> dict[str, Any]:
        return result(lambda: adapter.launch(deployment_id, operation_id))

    @server.tool(name=TERMINAL_TOOL_NAMES[6], description="Read your asynchronous launch receipt, not live health. outcome_unknown requires the operator; never retry with a fresh ID.", annotations=read)
    def launch_status(deployment_id: str, operation_id: str) -> dict[str, Any]:
        return result(lambda: adapter.launch_status(deployment_id, operation_id))
    return server


def main(data_dir: Path | None = None, *, terminal_access=False) -> int:
    try:
        server = create_terminal_server(data_dir) if terminal_access else create_server(data_dir)
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
