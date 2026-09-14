"""Pinned-SSH execution of a deliberately small matrixd command surface."""

from __future__ import annotations

import json
import re

from matrix_gui.modules.railgun.ssh_support import connect_ssh_profile


MATRIXD = "/matrix/.venv/bin/python3 /matrix/scripts/matrixd"
LIST_COMMAND = (
    'if [ "$(id -u)" -eq 0 ]; then '
    f"exec {MATRIXD} list --json; "
    "elif command -v sudo >/dev/null 2>&1; then "
    f"exec /usr/bin/sudo -n {MATRIXD} list --json; "
    "else exit 77; fi"
)
MAX_OUTPUT_BYTES = 1024 * 1024
_UNIVERSE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def parse_snapshot(payload: str) -> list[dict]:
    """Validate the bounded public schema from ``matrixd list --json``."""
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("matrixd inventory is missing or too large")
    try:
        document = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("matrixd returned invalid inventory JSON") from exc
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError("matrixd inventory version is unsupported")
    values = document.get("universes")
    if not isinstance(values, list) or len(values) > 1024:
        raise ValueError("matrixd universe inventory is invalid")

    result = []
    seen = set()
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("matrixd universe entry is invalid")
        universe = value.get("universe")
        count = value.get("agent_count")
        rss = value.get("rss_bytes", 0)
        cpu = value.get("cpu_percent", 0)
        if not isinstance(universe, str) or not _UNIVERSE.fullmatch(universe):
            raise ValueError("matrixd returned an invalid universe name")
        if universe in seen:
            raise ValueError("matrixd returned a duplicate universe")
        if value.get("status") != "active":
            raise ValueError("matrixd returned an invalid universe status")
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 100000:
            raise ValueError("matrixd returned an invalid agent count")
        if (
            isinstance(rss, bool)
            or not isinstance(rss, int)
            or rss < 0
            or isinstance(cpu, bool)
            or not isinstance(cpu, (int, float))
            or cpu < 0
        ):
            raise ValueError("matrixd returned invalid resource totals")
        seen.add(universe)
        result.append(
            {
                "universe": universe,
                "status": "active",
                "agent_count": count,
                "rss_bytes": rss,
                "cpu_percent": float(cpu),
            }
        )
    return sorted(result, key=lambda item: item["universe"].lower())


def build_kill_command(universe: str) -> str:
    """Build one fixed, universe-scoped stop command without shell input."""
    if not isinstance(universe, str) or not _UNIVERSE.fullmatch(universe):
        raise ValueError("invalid universe name")
    command = f"{MATRIXD} kill --universe {universe}"
    return (
        'if [ "$(id -u)" -eq 0 ]; then '
        f"exec {command}; "
        "elif command -v sudo >/dev/null 2>&1; then "
        f"exec /usr/bin/sudo -n {command}; "
        "else exit 77; fi"
    )


def _exec(client, command: str, timeout: int) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read(MAX_OUTPUT_BYTES + 1)
    error = stderr.read(65537)
    exit_code = stdout.channel.recv_exit_status()
    if len(output) > MAX_OUTPUT_BYTES or len(error) > 65536:
        raise RuntimeError("remote matrixd output exceeded its safety limit")
    if exit_code != 0:
        raise RuntimeError(f"remote matrixd command failed with status {exit_code}")
    if error.strip():
        raise RuntimeError("remote matrixd command wrote to stderr")
    return output.decode("utf-8", errors="strict")


def _list(client, timeout: int) -> list[dict]:
    return parse_snapshot(_exec(client, LIST_COMMAND, timeout))


def perform(profile: dict, operation: str, universe: str | None = None) -> dict:
    """Connect once, execute a bounded operation, and return a fresh inventory."""
    if operation not in {"list", "kill", "kill_all"}:
        raise ValueError("unsupported swarm operation")
    client, fingerprint = connect_ssh_profile(profile, timeout=15)
    try:
        stopped = []
        failed = []
        if operation == "list":
            inventory = _list(client, 30)
        elif operation == "kill":
            build_kill_command(universe)  # validate before issuing any command
            _exec(client, build_kill_command(universe), 120)
            stopped.append(universe)
            inventory = _list(client, 30)
        else:
            before = _list(client, 30)
            # Kill All means exactly the active universes returned by this
            # pinned server in this same SSH connection. Nothing is deleted.
            for item in before:
                target = item["universe"]
                try:
                    _exec(client, build_kill_command(target), 120)
                    stopped.append(target)
                except Exception:
                    # Continue the explicitly requested global stop, but return
                    # exact failed universe names after refreshing inventory.
                    failed.append(target)
            inventory = _list(client, 30)
        return {
            "universes": inventory,
            "stopped": stopped,
            "failed": failed,
            "fingerprint": fingerprint,
        }
    finally:
        client.close()
