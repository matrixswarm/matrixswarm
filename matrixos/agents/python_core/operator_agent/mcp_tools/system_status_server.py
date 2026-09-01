"""Read-only host telemetry MCP server for the Operator Agent pilot.

The server deliberately exposes one no-argument tool.  It never accepts a
path, command, service name, environment variable, or other host-controlled
input, and it has no mutation capability.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


def _read_limited(path: Path, limit: int = 16_384) -> str:
    """Read a fixed procfs file with a bounded result size."""
    with path.open("r", encoding="ascii", errors="replace") as source:
        return source.read(limit)


def _memory_snapshot() -> dict[str, int] | None:
    """Return selected memory counters without exposing raw procfs contents."""
    try:
        values: dict[str, int] = {}
        for line in _read_limited(Path("/proc/meminfo")).splitlines():
            key, separator, remainder = line.partition(":")
            if not separator:
                continue
            value = remainder.strip().split(maxsplit=1)
            if value and value[0].isdigit():
                values[key] = int(value[0]) * 1024
        if "MemTotal" not in values or "MemAvailable" not in values:
            return None
        return {
            "total_bytes": values["MemTotal"],
            "available_bytes": values["MemAvailable"],
            "used_bytes": max(0, values["MemTotal"] - values["MemAvailable"]),
        }
    except OSError:
        return None


def _uptime_seconds() -> int | None:
    try:
        value = _read_limited(Path("/proc/uptime"), 128).split(maxsplit=1)[0]
        return max(0, int(float(value)))
    except (IndexError, OSError, ValueError):
        return None


def _root_filesystem() -> dict[str, int] | None:
    try:
        status = os.statvfs("/")
        block_size = status.f_frsize or status.f_bsize
        total = status.f_blocks * block_size
        available = status.f_bavail * block_size
        return {
            "total_bytes": total,
            "available_bytes": available,
            "used_bytes": max(0, total - (status.f_bfree * block_size)),
        }
    except OSError:
        return None


def system_status() -> dict[str, Any]:
    """Return a bounded, read-only snapshot of basic host health."""
    try:
        load_average = [round(value, 2) for value in os.getloadavg()]
    except OSError:
        load_average = None
    return {
        "observed_at": int(time.time()),
        "uptime_sec": _uptime_seconds(),
        "load_average": load_average,
        "memory": _memory_snapshot(),
        "root_filesystem": _root_filesystem(),
    }


def _create_server():
    """Import the MCP SDK only in the isolated MCP worker environment."""
    from mcp.server import MCPServer

    server = MCPServer("matrixswarm-system-status")

    @server.tool()
    def read_status() -> dict[str, Any]:
        """Read host uptime, load, memory, and root filesystem capacity."""
        return system_status()

    return server


if __name__ == "__main__":
    _create_server().run(transport="stdio")
