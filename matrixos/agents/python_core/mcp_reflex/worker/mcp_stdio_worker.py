#!/usr/bin/env python3
"""One-shot stdio worker for an external MCP server."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from typing import Any, Mapping


class RequestError(ValueError):
    """Invalid bridge request."""


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RequestError(f"{field} must be a mapping")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RequestError(f"{field} must be a non-empty string")
    return value


def _server(value: Any) -> dict[str, Any]:
    raw = _mapping(value, "server")
    command = _string(raw.get("command"), "server.command")
    if not command.startswith("/") or any(
        control in command for control in ("\x00", "\r", "\n")
    ):
        raise RequestError("server.command must be an absolute path")
    args, env, timeout = raw.get("args", []), raw.get("env", {}), raw.get("timeout_sec", 30)
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise RequestError("server.args must be a list of strings")
    if not isinstance(env, Mapping) or not all(isinstance(key, str) and isinstance(item, str) for key, item in env.items()):
        raise RequestError("server.env must be a string mapping")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300:
        raise RequestError("server.timeout_sec must be an integer from 1 to 300")
    return {"command": command, "args": args, "env": dict(env), "timeout_sec": timeout}


def _jsonable(value: Any) -> Any:
    return value.model_dump(by_alias=True, mode="json") if hasattr(value, "model_dump") else value


async def _run_mcp(request: Mapping[str, Any]) -> Any:
    from mcp import Client, StdioServerParameters

    operation = _string(request.get("operation"), "operation")
    server = _server(request.get("server"))
    permitted_tools = request.get("permitted_tools")
    if not isinstance(permitted_tools, list) or not all(isinstance(name, str) for name in permitted_tools):
        raise RequestError("permitted_tools must be a list of strings")

    tool_name = None
    arguments: Mapping[str, Any] = {}
    if operation == "call_tool":
        tool_name = _string(request.get("tool_name"), "tool_name")
        if tool_name not in permitted_tools:
            raise RequestError("tool is not permitted")
        arguments = request.get("arguments", {})
        if not isinstance(arguments, Mapping):
            raise RequestError("arguments must be a mapping")
    elif operation != "list_tools":
        raise RequestError("unsupported operation")

    parameters = StdioServerParameters(command=server["command"], args=server["args"], env=server["env"])
    async with Client(parameters) as client:
        if operation == "list_tools":
            listed = await client.list_tools()
            tools = [_jsonable(tool) for tool in listed.tools]
            return {"tools": [tool for tool in tools if isinstance(tool, Mapping) and tool.get("name") in permitted_tools]}
        return _jsonable(await client.call_tool(tool_name, dict(arguments)))


async def _with_timeout(request: Mapping[str, Any]) -> Any:
    server = _server(request.get("server"))
    async with asyncio.timeout(server["timeout_sec"]):
        return await _run_mcp(request)


def _respond(payload: Mapping[str, Any]) -> int:
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
    return 0


def main() -> int:
    try:
        request = _mapping(json.loads(sys.stdin.buffer.readline().decode("utf-8")), "request")
        if request.get("operation") == "health":
            return _respond({"ok": True, "result": {"sdk_available": importlib.util.find_spec("mcp") is not None}})
        return _respond({"ok": True, "result": asyncio.run(_with_timeout(request))})
    except Exception as exc:
        return _respond({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    raise SystemExit(main())
