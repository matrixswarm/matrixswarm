# MCP Reflex

MCP Reflex is MatrixSwarm's signed, default-deny airlock for external MCP
servers. Matrix agents never import the MCP SDK. Each approved request crosses
an argument-free, root-owned launcher into a separate non-login Linux account.

## Deployment policy

Add `mcp_reflex` to the compiled directive and configure exact servers, tools,
and caller UIDs. There are no wildcard grants.

```json
{
  "servers": {
    "example": {
      "command": "/opt/mcp/example/bin/server",
      "args": ["--stdio"],
      "env": {},
      "allowed_tools": ["status", "lookup"],
      "timeout_sec": 30
    }
  },
  "access_control": {
    "default": "deny",
    "callers": {
      "trusted-agent-uid": {
        "servers": {
          "example": ["status"]
        }
      }
    }
  }
}
```

The effective grant is the intersection of the server's `allowed_tools` and
the exact caller grant. Unknown callers, servers, and tools fail closed.

## Matrix commands

- `hive.mcp.tools@cmd_mcp_list_tools`
  - content: `{"request_id":"unique-id","server_id":"example"}`
- `hive.mcp.call_tool@cmd_mcp_call_tool`
  - content: `{"request_id":"unique-id","server_id":"example","tool_name":"status","arguments":{}}`

Replies use `cmd_mcp_result`. Request IDs are scoped to the authenticated
sender and retained for a bounded replay window after completion.

## Authenticated probe

`mcp_reflex_probe` is an opt-in, one-shot validation agent built on the
reusable `McpReflexClientMixin`. It resolves MCP Reflex through the service
registry and sends packets directly to that endpoint, preserving the probe's
signed identity instead of turning Matrix into an MCP proxy.

For the root-owned smoke server at
`/opt/matrixswarm/mcp-smoke/echo_server.py`, configure the MCP Reflex node with
the probe node's exact deployed UID:

```json
{
  "servers": {
    "smoke": {
      "command": "/matrix/mcp/.venv/bin/python3",
      "args": ["/opt/matrixswarm/mcp-smoke/echo_server.py"],
      "env": {},
      "allowed_tools": ["echo", "hidden"],
      "timeout_sec": 15
    }
  },
  "access_control": {
    "default": "deny",
    "callers": {
      "mcp-reflex-probe-EXACT-DEPLOYED-UID": {
        "servers": {"smoke": ["echo"]}
      }
    }
  }
}
```

Set the probe node's `run_on_boot` to `true`. A successful run logs one final
`[MCP-PROBE] ✅ PASS` line after verifying filtered discovery, an authorized
echo, a denied `hidden` call, and the signed callback from MCP Reflex.

## Runtime boundary

Railgun installs the MCP SDK only in `/matrix/mcp/.venv`, creates a distinct
`matrix-<universe>-mcp` account, and grants the native universe account one
exact sudo command: `/usr/local/libexec/matrix-mcp-launch`. The launcher accepts
no arguments, verifies its root-owned profile and worker hash, applies process,
memory, CPU, descriptor, and output limits, sets `no_new_privs`, clears groups,
drops UID/GID, and starts the one-shot bridge in a private working directory.

This is OS-account and process isolation, not a network or filesystem
namespace. MCP servers can still reach resources available to that restricted
Linux account, so install and configure them with the same care as any other
untrusted service integration.
