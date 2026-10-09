"""Explicit tool routes for approved scopes; never infer resource URIs."""


def permitted_calls(deployment_id, operations):
    operations = set(operations)
    routes = (
        ("swarms.list", "phoenix_terminal_swarms"),
        ("agents.list", "phoenix_terminal_agents"),
        ("sessions.list", "phoenix_terminal_sessions"),
        ("sessions.open", "phoenix_terminal_connect"),
        ("alerts.read", "phoenix_terminal_alerts"),
    )
    calls = [{"tool_name": tool, "arguments": {"deployment_id": deployment_id}}
             for operation, tool in routes if operation in operations]
    if {"agents.list", "logs.read"}.issubset(operations):
        calls.append({"tool_name": "phoenix_terminal_inspect",
                      "arguments": {"deployment_id": deployment_id}})
    if "logs.read" in operations:
        calls.append({"tool_name": "phoenix_terminal_logs",
                      "arguments": {"deployment_id": deployment_id},
                      "additional_required_argument": "agent_id: use an exact ID returned by phoenix_terminal_agents"})
    if "railgun.launch" in operations:
        for tool in ("phoenix_terminal_railgun_launch", "phoenix_terminal_railgun_status"):
            calls.append({"tool_name": tool, "arguments": {"deployment_id": deployment_id},
                          "additional_required_argument": "operation_id: retain one 32-character lowercase hex ID per intentional launch; reuse on retries"})
    return calls
