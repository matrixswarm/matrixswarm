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
    CommandHint("terminal", "Request approval, inspect bounded swarm diagnostics, and list/open permitted Phoenix cockpit sessions.", ("operator-opened Terminal desktop runtime", "saved per-deployment operation permission", "same private local state directory", "updated MatrixOS diagnostic commands for agents/logs/inspect"), "medium", False, True, ("terminal doctor diagnoses without requesting access", "terminal status returns exact IDs and scopes", "terminal inspect requires both agents.list and logs.read", "Connect opens a cockpit tab; Railgun is a separate inactive-only boot", "lock/disconnect/expiry revokes approval"), "disconnect or ask the operator to lock Terminal access; existing cockpit tabs remain operator-owned", "experimental: approval, alerts, swarm/agent inventory, bounded logs, inspection and cockpit Connect; no restarts or edits"),
    CommandHint("bridge", "Read operator-selected saved inventory through the headless console, not the GUI.", ("operator-enabled headless inventory session",), "low", False, False, ("mode and expiry", "selected public IDs"), "lock the operator console", "partial: inventory only"),
    CommandHint("investigation", "Retired GUI prototype; no current headless investigation or evidence adapter.", ("future standalone evidence adapter",), "low", False, False, (), "Not available", "unavailable"),
    CommandHint("mcp", "Expose approved Terminal tools with --terminal-access, or legacy saved-inventory tools without it.", ("MCP optional dependency", "matching operator runtime and local state directory"), "medium", False, True, ("phoenix_terminal_request requires operator approval", "phoenix_terminal_status supplies effective scopes", "plain mcp uses the separate legacy inventory endpoint"), "disconnect or lock the matching runtime", "partial: approved Terminal adapters or legacy inventory"),
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
