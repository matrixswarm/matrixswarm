"""Validation and state transitions for Harvester matrixd observations."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from typing import Any


class HarvesterPolicyError(ValueError):
    """A Harvester target, snapshot, or state violates fail-closed policy."""


_TARGET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_UNIVERSE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def normalize_target(value: Any) -> dict[str, Any]:
    """Return one bounded universe target containing no connection material."""
    if not isinstance(value, Mapping):
        raise HarvesterPolicyError("target must be a mapping")
    target_id = _identifier(value.get("id"), "target id", _TARGET_ID)
    universe = _identifier(value.get("universe"), "universe", _UNIVERSE)
    note = value.get("note", "")
    if not isinstance(note, str) or len(note) > 128 or _has_control(note):
        raise HarvesterPolicyError("target note is invalid")
    recovery_mode = value.get("recovery_mode", "disabled")
    if recovery_mode not in {"disabled", "automatic"}:
        raise HarvesterPolicyError("recovery_mode must be disabled or automatic")
    normalized = {
        "id": target_id,
        "universe": universe,
        "note": note.strip(),
        "confirm_healthy_once": value.get("confirm_healthy_once") is True,
        "minimum_agents": _bounded_int(value, "minimum_agents", 1, 1, 10_000),
        "failure_threshold": _bounded_int(value, "failure_threshold", 3, 1, 20),
        "recovery_threshold": _bounded_int(value, "recovery_threshold", 3, 1, 20),
        "alert_cooldown_sec": _bounded_int(
            value, "alert_cooldown_sec", 300, 0, 86_400
        ),
        "recovery_mode": recovery_mode,
        "recovery_attempt_limit": _bounded_int(
            value, "recovery_attempt_limit", 3, 1, 10
        ),
        "recovery_cooldown_sec": _bounded_int(
            value, "recovery_cooldown_sec", 60, 10, 3_600
        ),
    }
    if recovery_mode == "automatic":
        normalized.update(_normalize_recovery_capability(value, universe))
    return normalized


def parse_matrixd_snapshot(
    payload: str, *, maximum_bytes: int = 1_048_576
) -> dict[str, dict[str, Any]]:
    """Parse the bounded public schema emitted by ``matrixd list --json``."""
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > maximum_bytes:
        raise HarvesterPolicyError("matrixd snapshot is missing or too large")
    try:
        decoded = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise HarvesterPolicyError("matrixd snapshot is invalid JSON") from exc
    if not isinstance(decoded, Mapping) or decoded.get("version") != 1:
        raise HarvesterPolicyError("matrixd snapshot version is unsupported")
    universes = decoded.get("universes")
    if not isinstance(universes, list) or len(universes) > 1_024:
        raise HarvesterPolicyError("matrixd universe list is invalid")

    result = {}
    for entry in universes:
        if not isinstance(entry, Mapping):
            raise HarvesterPolicyError("matrixd universe entry is invalid")
        universe = _identifier(
            entry.get("universe"), "snapshot universe", _UNIVERSE
        )
        status = entry.get("status")
        count = entry.get("agent_count")
        if status != "active" or isinstance(count, bool) or not isinstance(count, int):
            raise HarvesterPolicyError("matrixd universe status is invalid")
        if not 0 <= count <= 100_000 or universe in result:
            raise HarvesterPolicyError("matrixd universe count or identity is invalid")
        result[universe] = {"status": status, "agent_count": count}
    return result


def observation_for_target(
    target: Mapping[str, Any], universes: Mapping[str, Mapping[str, Any]]
) -> tuple[bool, str]:
    entry = universes.get(target["universe"])
    if entry is None:
        return False, "UNIVERSE_ABSENT"
    count = entry["agent_count"]
    minimum = target["minimum_agents"]
    if count < minimum:
        return False, f"AGENTS_{count}_BELOW_{minimum}"
    return True, f"ACTIVE_{count}_AGENTS"


def initial_state() -> dict[str, Any]:
    return {
        "status": "unknown",
        "failure_hits": 0,
        "recovery_hits": 0,
        "last_alert_at": None,
        "recovery_attempts": 0,
        "last_recovery_at": None,
    }


def evaluate_observation(
    state: Mapping[str, Any],
    *,
    success: bool,
    observed_at: float,
    target: Mapping[str, Any],
) -> tuple[dict[str, Any], str | None]:
    current = str(state.get("status", "unknown"))
    if current not in {"unknown", "up", "down"}:
        raise HarvesterPolicyError("target state is invalid")
    next_state = {
        "status": current,
        "failure_hits": _counter(state.get("failure_hits", 0)),
        "recovery_hits": _counter(state.get("recovery_hits", 0)),
        "last_alert_at": state.get("last_alert_at"),
        "recovery_attempts": _counter(state.get("recovery_attempts", 0)),
        "last_recovery_at": state.get("last_recovery_at"),
    }
    if success:
        next_state["failure_hits"] = 0
        if current == "down":
            next_state["recovery_hits"] += 1
            if next_state["recovery_hits"] >= target["recovery_threshold"]:
                next_state.update(
                    status="up",
                    recovery_hits=0,
                    last_alert_at=observed_at,
                    recovery_attempts=0,
                    last_recovery_at=None,
                )
                return next_state, "RECOVERY"
        else:
            next_state.update(status="up", recovery_hits=0)
            if current == "unknown" and target["confirm_healthy_once"]:
                return next_state, "HEALTHY"
        return next_state, None

    next_state["recovery_hits"] = 0
    next_state["failure_hits"] += 1
    if current != "down" and next_state["failure_hits"] >= target["failure_threshold"]:
        next_state.update(status="down", last_alert_at=observed_at)
        return next_state, "DOWN"
    if current == "down":
        last_alert = next_state["last_alert_at"]
        if (
            last_alert is None
            or observed_at - float(last_alert) >= target["alert_cooldown_sec"]
        ):
            next_state["last_alert_at"] = observed_at
            return next_state, "DOWN_REMINDER"
    return next_state, None


def recovery_due(
    state: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    globally_enabled: bool,
    collection_available: bool,
    observed_at: float,
) -> bool:
    return (
        globally_enabled is True
        and collection_available is True
        and state.get("status") == "down"
        and target.get("recovery_mode") == "automatic"
        and state.get("recovery_attempts", 0) < target["recovery_attempt_limit"]
        and (
            state.get("last_recovery_at") is None
            or observed_at - float(state["last_recovery_at"])
            >= target["recovery_cooldown_sec"]
        )
    )


def record_recovery_attempt(
    state: Mapping[str, Any], *, observed_at: float
) -> dict[str, Any]:
    updated = dict(state)
    updated["recovery_attempts"] = _counter(
        updated.get("recovery_attempts", 0)
    ) + 1
    updated["last_recovery_at"] = observed_at
    return updated


def _normalize_recovery_capability(
    value: Mapping[str, Any], universe: str
) -> dict[str, str]:
    linux_user = value.get("linux_user")
    if (
        not isinstance(linux_user, str)
        or not re.fullmatch(r"matrix-[a-z0-9_-]{1,24}", linux_user)
    ):
        raise HarvesterPolicyError("automatic recovery requires a matrix-* Linux user")
    expected_path = f"/matrix/boot_directives/{universe}.enc.json"
    directive_path = value.get("directive_path", expected_path)
    if directive_path != expected_path:
        raise HarvesterPolicyError("automatic recovery directive path is invalid")
    swarm_key = value.get("swarm_key")
    if not isinstance(swarm_key, str):
        raise HarvesterPolicyError("automatic recovery requires a swarm key")
    try:
        decoded = base64.b64decode(swarm_key, validate=True)
    except ValueError as exc:
        raise HarvesterPolicyError("automatic recovery swarm key is invalid") from exc
    if not 16 <= len(decoded) <= 64:
        raise HarvesterPolicyError("automatic recovery swarm key length is invalid")
    return {
        "linux_user": linux_user,
        "directive_path": expected_path,
        "swarm_key": swarm_key,
    }


def _identifier(value: Any, field: str, pattern) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise HarvesterPolicyError(f"{field} is invalid")
    return value


def _bounded_int(
    value: Mapping[str, Any], field: str, default: int, minimum: int, maximum: int
) -> int:
    candidate = value.get(field, default)
    if isinstance(candidate, bool) or not isinstance(candidate, int):
        raise HarvesterPolicyError(f"{field} must be an integer")
    if not minimum <= candidate <= maximum:
        raise HarvesterPolicyError(f"{field} is outside its safe range")
    return candidate


def _counter(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HarvesterPolicyError("target counter is invalid")
    return value


def _has_control(value: str) -> bool:
    return any(character in value for character in ("\x00", "\r", "\n"))
