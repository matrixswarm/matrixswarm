"""Pure validation helpers for the approval-gated operator agent editor."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, Mapping


class OperatorAgentConfigError(ValueError):
    """The editor attempted to save an unsafe operator-agent policy."""


_name_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _name_re.fullmatch(value.strip()):
        raise OperatorAgentConfigError(f"{field} must be a safe non-empty identifier")
    return value.strip()


def exact_uids(value: Any, field: str) -> list[str]:
    """Canonicalize an explicit list of deployed agent UIDs."""
    if not isinstance(value, list):
        raise OperatorAgentConfigError(f"{field} must be a list")
    result = sorted({_name(item, field) for item in value})
    if not result:
        raise OperatorAgentConfigError(f"{field} must contain at least one exact UID")
    return result


def validate_workflows(value: Any) -> dict[str, dict[str, Any]]:
    """Validate fixed, approval-required MCP workflows."""
    if not isinstance(value, Mapping):
        raise OperatorAgentConfigError("workflows must be a mapping")
    result: dict[str, dict[str, Any]] = {}
    for raw_id, raw in value.items():
        workflow_id = _name(raw_id, "workflow ID")
        if not isinstance(raw, Mapping):
            raise OperatorAgentConfigError(f"workflow {workflow_id} must be a mapping")
        server_id = _name(raw.get("server_id"), f"{workflow_id}.server_id")
        tool_name = _name(raw.get("tool_name"), f"{workflow_id}.tool_name")
        arguments = raw.get("arguments", {})
        if not isinstance(arguments, Mapping):
            raise OperatorAgentConfigError(f"{workflow_id}.arguments must be a JSON mapping")
        try:
            encoded = json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise OperatorAgentConfigError(f"{workflow_id}.arguments must be JSON-compatible") from exc
        if len(encoded) > 131_072:
            raise OperatorAgentConfigError(f"{workflow_id}.arguments exceed 128 KiB")
        if raw.get("requires_approval") is not True:
            raise OperatorAgentConfigError(f"{workflow_id} must require approval")
        turns = raw.get("turn_budget", 1)
        if isinstance(turns, bool) or not isinstance(turns, int) or not 1 <= turns <= 128:
            raise OperatorAgentConfigError(f"{workflow_id}.turn_budget must be from 1 to 128")
        result[workflow_id] = {
            "server_id": server_id,
            "tool_name": tool_name,
            "arguments": deepcopy(dict(arguments)),
            "requires_approval": True,
            "turn_budget": turns,
        }
    if not result:
        raise OperatorAgentConfigError("configure at least one fixed workflow before enabling")
    return result


def validated_operator_policy(
    *,
    enabled: Any,
    requesters: Any,
    approvers: Any,
    workflows: Any,
    limits: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a canonical, two-party, fail-closed operator policy."""
    if enabled is not True:
        return {
            "enabled": False,
            "require_distinct_approver": True,
            "authorized_requester_uids": [],
            "authorized_approver_uids": [],
            "workflows": {},
            **_validated_limits(limits),
        }
    requester_uids = exact_uids(requesters, "requester UID")
    approver_uids = exact_uids(approvers, "approver UID")
    if set(requester_uids) == set(approver_uids):
        raise OperatorAgentConfigError(
            "requesters and approvers cannot be the same identity set"
        )
    return {
        "enabled": True,
        "require_distinct_approver": True,
        "authorized_requester_uids": requester_uids,
        "authorized_approver_uids": approver_uids,
        "workflows": validate_workflows(workflows),
        **_validated_limits(limits),
    }


def _validated_limits(limits: Mapping[str, Any]) -> dict[str, int]:
    defaults = {
        "max_active_runs": (8, 1, 64),
        "max_retained_runs": (128, 1, 1_024),
        "default_turn_budget": (4, 1, 128),
        "max_pending_mcp_requests": (8, 1, 128),
        "mcp_request_timeout_sec": (60, 1, 600),
    }
    result: dict[str, int] = {}
    for name, (default, minimum, maximum) in defaults.items():
        value = limits.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise OperatorAgentConfigError(f"{name} must be from {minimum} to {maximum}")
        result[name] = value
    if result["max_retained_runs"] < result["max_active_runs"]:
        raise OperatorAgentConfigError("max_retained_runs must cover max_active_runs")
    return result
