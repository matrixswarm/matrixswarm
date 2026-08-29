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
