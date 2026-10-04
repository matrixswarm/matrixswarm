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
    CommandHint("terminal", "Request operator-approved read-only live swarm alerts from immutable saved WSS targets.", ("operator-opened Terminal desktop runtime", "saved per-deployment alerts.read permission", "shared private local state directory"), "low", False, True, ("no remote connection before approval", "only permitted resource IDs in terminal status", "source.state/code distinguish disconnection from silence", "lock/disconnect/expiry revokes approval"), "disconnect or ask the operator to lock Terminal access", "partial: approval and live alerts; no logs, commands or deployment actions"),
    CommandHint("bridge", "Read operator-selected saved inventory through the headless console, not the GUI.", ("operator-enabled headless inventory session",), "low", False, False, ("mode and expiry", "selected public IDs"), "lock the operator console", "partial: inventory only"),
    CommandHint("investigation", "Retired GUI prototype; no current headless investigation or evidence adapter.", ("future standalone evidence adapter",), "low", False, False, (), "Not available", "unavailable"),
    CommandHint("mcp", "Expose five read-only headless inventory operations to a local MCP client.", ("MCP optional dependency", "operator-enabled headless inventory session"), "low", False, False, ("read-only tool annotations", "assignment expiry"), "lock the operator console", "partial: inventory only"),
    CommandHint("vault", "Open an operator-prepared password vault without Qt and share selected read-only inventory; writes and remote actions remain unavailable.", ("trusted Phoenix crypto source", "private interactive operator terminal", "explicit selection and expiring enable confirmation"), "medium", False, True, ("access off until enabled", "only selected public IDs", "lock/expiry revokes endpoint"), "lock or exit the operator console; vault file remains unchanged", "partial: inventory only"),
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
