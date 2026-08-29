"""Pure exact-allowlist policy used by the MatrixSwarm MCP airlock."""

from __future__ import annotations

from typing import Any, Mapping


class PolicyError(ValueError):
    """Raised when an MCP deployment policy is malformed or denies a request."""


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyError(f"{field} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field: str) -> set[str]:
    if not isinstance(value, list) or not value:
        raise PolicyError(f"{field} must be a non-empty list")
    return {_string(item, field) for item in value}


def server_config(config: Mapping[str, Any], server_id: str) -> dict[str, Any]:
    """Return validated deployment-owned configuration for one MCP server."""
    server_id = _string(server_id, "server_id")
    servers = config.get("servers")
    if not isinstance(servers, Mapping):
        raise PolicyError("servers must be a mapping")
    raw = servers.get(server_id)
    if not isinstance(raw, Mapping):
        raise PolicyError("unknown server_id")
    command = _string(raw.get("command"), "server.command")
    if not command.startswith("/") or any(
        control in command for control in ("\x00", "\r", "\n")
    ):
        raise PolicyError("server.command must be an absolute path")
    args, env, timeout = raw.get("args", []), raw.get("env", {}), raw.get("timeout_sec", 30)
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise PolicyError("server.args must be a list of strings")
    if not isinstance(env, Mapping) or not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items()):
        raise PolicyError("server.env must be a string mapping")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300:
        raise PolicyError("timeout_sec must be an integer from 1 to 300")
    return {
        "command": command, "args": list(args), "env": dict(env),
        # Keep the validated deployment policy JSON-serializable because this
        # structure crosses the one-shot worker's stdio boundary.
        "allowed_tools": sorted(
            _string_list(raw.get("allowed_tools"), "server.allowed_tools")
        ),
        "timeout_sec": timeout,
    }


def allowed_tools(config: Mapping[str, Any], caller_uid: str, server_id: str) -> set[str]:
    """Return intersection of exact caller and server grants; no wildcards."""
    caller_uid, server_id = _string(caller_uid, "caller_uid"), _string(server_id, "server_id")
    server_tools = set(server_config(config, server_id)["allowed_tools"])
    access = config.get("access_control")
    if not isinstance(access, Mapping) or not isinstance(access.get("callers"), Mapping):
        raise PolicyError("access_control.callers must be a mapping")
    caller = access["callers"].get(caller_uid)
    if not isinstance(caller, Mapping) or not isinstance(caller.get("servers"), Mapping):
        raise PolicyError("caller is not authorized")
    caller_tools = _string_list(caller["servers"].get(server_id), "caller server grant")
    return server_tools.intersection(caller_tools)


def authorize_tool(config: Mapping[str, Any], caller_uid: str, server_id: str, tool_name: str) -> dict[str, Any]:
    if _string(tool_name, "tool_name") not in allowed_tools(config, caller_uid, server_id):
        raise PolicyError("tool is not authorized")
    return server_config(config, server_id)
