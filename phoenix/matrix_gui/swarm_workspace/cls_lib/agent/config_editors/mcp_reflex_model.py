"""Pure configuration helpers for the Phoenix MCP Reflex editor."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


class McpReflexConfigError(ValueError):
    """Raised when the editor would save an unsafe or malformed policy."""


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise McpReflexConfigError(f"{field} must be a non-empty string")
    result = value.strip()
    if len(result) > 128 or any(char in result for char in ("\x00", "\r", "\n")):
        raise McpReflexConfigError(f"{field} contains invalid characters")
    return result


def _tool_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise McpReflexConfigError(f"{field} must be a list")
    tools = sorted({_name(tool, field) for tool in value})
    if not tools:
        raise McpReflexConfigError(f"{field} must contain at least one tool")
    return tools


def validate_servers(value: Any) -> dict[str, dict[str, Any]]:
    """Return a safe deep copy of deployment-owned MCP server definitions."""
    if not isinstance(value, Mapping):
        raise McpReflexConfigError("servers must be a mapping")
    servers: dict[str, dict[str, Any]] = {}
    for raw_id, raw in value.items():
        server_id = _name(raw_id, "server id")
        if not isinstance(raw, Mapping):
            raise McpReflexConfigError(f"server {server_id} must be a mapping")
        command = _name(raw.get("command"), f"{server_id}.command")
        if not command.startswith("/"):
            raise McpReflexConfigError(
                f"{server_id}.command must be an absolute Linux path"
            )
        args = raw.get("args", [])
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise McpReflexConfigError(f"{server_id}.args must be a string list")
        env = raw.get("env", {})
        if not isinstance(env, Mapping) or not all(
            isinstance(key, str) and key and isinstance(item, str)
            for key, item in env.items()
        ):
            raise McpReflexConfigError(f"{server_id}.env must be a string mapping")
        timeout = raw.get("timeout_sec", 30)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300:
            raise McpReflexConfigError(
                f"{server_id}.timeout_sec must be an integer from 1 to 300"
            )
        servers[server_id] = {
            "command": command,
            "args": list(args),
            "env": dict(env),
            "allowed_tools": _tool_list(
                raw.get("allowed_tools"), f"{server_id}.allowed_tools"
            ),
            "timeout_sec": timeout,
        }
    return servers


def flatten_grants(access_control: Any) -> list[dict[str, Any]]:
    """Convert nested exact caller grants into editable table-style rows."""
    if not isinstance(access_control, Mapping):
        return []
    callers = access_control.get("callers", {})
    if not isinstance(callers, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for caller_uid, caller in callers.items():
        if not isinstance(caller, Mapping) or not isinstance(caller.get("servers"), Mapping):
            continue
        for server_id, tools in caller["servers"].items():
            rows.append({
                "caller_uid": str(caller_uid),
                "server_id": str(server_id),
                "tools": list(tools) if isinstance(tools, list) else [],
            })
    return rows


def build_access_control(
    grants: Any, servers: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Build a canonical default-deny policy from exact caller grant rows."""
    validated_servers = validate_servers(servers)
    if not isinstance(grants, list):
        raise McpReflexConfigError("caller grants must be a list")
    callers: dict[str, dict[str, dict[str, list[str]]]] = {}
    seen: set[tuple[str, str]] = set()
    for row in grants:
        if not isinstance(row, Mapping):
            raise McpReflexConfigError("each caller grant must be a mapping")
        caller_uid = _name(row.get("caller_uid"), "caller UID")
        server_id = _name(row.get("server_id"), "grant server id")
        if server_id not in validated_servers:
            raise McpReflexConfigError(f"grant references unknown server: {server_id}")
        key = (caller_uid, server_id)
        if key in seen:
            raise McpReflexConfigError(
                f"duplicate grant for {caller_uid} and {server_id}"
            )
        seen.add(key)
        tools = _tool_list(row.get("tools"), "caller grant tools")
        outside_allowlist = set(tools) - set(
            validated_servers[server_id]["allowed_tools"]
        )
        if outside_allowlist:
            raise McpReflexConfigError(
                f"grant contains tools outside {server_id}'s allowlist: "
                + ", ".join(sorted(outside_allowlist))
            )
        callers.setdefault(caller_uid, {"servers": {}})["servers"][server_id] = tools
    return {"default": "deny", "callers": callers}


def validated_policy(
    servers: Any, grants: Any
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Validate both halves together before the editor mutates its node."""
    safe_servers = validate_servers(deepcopy(servers))
    return safe_servers, build_access_control(deepcopy(grants), safe_servers)
