"""Machine-readable workflow hints for people and AI assistants.

This catalog is deliberately declarative: assistants can explain prerequisites,
risks, dry-run behavior, and rollback without inventing deployment semantics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CommandHint:
    name: str
    purpose: str
    prerequisites: tuple[str, ...]
    risk: str
    supports_dry_run: bool
    confirmation_required: bool
    post_checks: tuple[str, ...]
    rollback: str
    state: str


COMMANDS = (
    CommandHint("status", "Inspect a Phoenix workspace without changing it.", ("Phoenix source directory",), "none", False, False, (), "Not applicable", "available"),
    CommandHint("monitor", "Check operator-approved HTTP/HTTPS endpoints and record availability.", ("Configured URLs that you are authorized to monitor",), "low", False, False, ("HTTP status and latency",), "Not applicable", "available"),
    CommandHint("bridge", "Use explicitly enabled, redacted Phoenix capabilities without reading vault secrets.", ("Phoenix launched with bridge hooks", "unlocked vault", "operator-enabled bridge switch"), "medium", False, True, ("Phoenix activity indicator", "session state", "redacted results"), "turn off the Phoenix LLM Bridge switch", "available"),
    CommandHint("mcp", "Expose the exact Phoenix bridge allowlist to a local MCP client.", ("MCP optional dependency", "operator-enabled Phoenix bridge"), "medium", False, True, ("MCP tool annotations", "Phoenix activity indicator", "redacted results"), "disable the MCP server or turn off the Phoenix LLM Bridge switch", "available"),
    CommandHint("vault", "Manage encrypted deployment credentials without exposing secret material.", ("Verified vault compatibility contract",), "high", True, True, ("vault integrity",), "restore encrypted backup", "planned"),
    CommandHint("connection", "Validate and manage approved Phoenix connection definitions.", ("unlocked vault", "verified provider adapter"), "medium", True, True, ("connection health",), "restore prior definition", "planned"),
    CommandHint("directive", "Validate, preview, and compile a deployment directive.", ("validated template", "unlocked vault for encrypted output"), "medium", True, True, ("schema and target validation",), "retain previous directive", "planned"),
    CommandHint("deploy", "Plan and deploy a validated directive to approved targets.", ("validated directive", "tested connections", "explicit target authorization"), "high", True, True, ("deployment status", "agent health"), "deployment rollback adapter", "planned"),
    CommandHint("swarm", "Inspect or control the lifecycle of an authorized swarm.", ("verified MatrixSwarm runtime adapter",), "high", True, True, ("runtime health",), "restore previous runtime state", "planned"),
    CommandHint("agent", "Inspect agent state and perform a confirmed lifecycle action.", ("verified runtime adapter", "explicit agent identity"), "high", True, True, ("agent health and logs",), "restart or restore previous agent revision", "planned"),
    CommandHint("railgun", "Check or install MatrixOS on an explicitly authorized SSH target.", ("verified SSH adapter", "target ownership", "dry-run plan"), "critical", True, True, ("remote install health",), "remote uninstall/restore adapter", "planned"),
)


def as_jsonable() -> list[dict[str, object]]:
    return [asdict(command) for command in COMMANDS]


def find(name: str) -> CommandHint | None:
    return next((command for command in COMMANDS if command.name == name), None)
