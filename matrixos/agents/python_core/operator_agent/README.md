# Operator Agent

`operator_agent` is MatrixSwarm's first cognitive-agent shell.  It has no
direct process, shell, SDK, or MCP-worker access.  It composes the reusable
encrypted cognitive-run lifecycle with `McpReflexClientMixin`; MCP Reflex still
performs identity, server, tool, and OS-isolation enforcement.

## Deliberate v1 boundary

An operator request names a configured workflow only.  The workflow owns the
MCP server, tool, and complete argument mapping.  Request packets cannot add
or override arguments.  A second, exact signed identity approves the run
before it crosses the airlock.  A requester cannot approve its own run unless
that safeguard is explicitly disabled (it is enabled by default).

The agent is disabled and has no authorized identities or workflows by
default.  It remains inert until an operator intentionally provisions all of
the following:

1. The exact deployed requester and approver UIDs.
2. A fixed, approval-required workflow.
3. The same exact deployed `operator_agent` UID in the MCP Reflex caller
   grants, with the workflow's server and tool.

Example operator configuration (replace all UIDs with current deployed UIDs):

```json
{
  "enabled": true,
  "authorized_requester_uids": ["request-broker-EXACT-UID"],
  "authorized_approver_uids": ["approval-console-EXACT-UID"],
  "workflows": {
    "read_status": {
      "server_id": "system_status",
      "tool_name": "read_status",
      "arguments": {},
      "requires_approval": true,
      "turn_budget": 1
    }
  }
}
```

The matching MCP Reflex policy grants only the tool needed by that workflow:

```json
{
  "access_control": {
    "default": "deny",
    "callers": {
      "operator-agent-EXACT-DEPLOYED-UID": {
        "servers": {"system_status": ["read_status"]}
      }
    }
  }
}
```

The cognitive checkpoint is encrypted under the agent's Phoenix-provisioned
symmetric key.  If a process restarts while an MCP request is in flight, that
run moves to `recovery_required`; it is never replayed automatically.
