"""Bounded, redacted swarm-alert pages for an approved Terminal session."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import threading
import re
from typing import Any

from .bridge.sanitize import redact_log_line


MAX_ALERTS_PER_DEPLOYMENT = 500
MAX_ALERT_PAGE = 200
MAX_ALERT_TEXT = 4000
PACKET_REJECTION_REASONS = frozenset({
    "FRAME_TOO_LARGE", "MALFORMED_PACKET", "UNEXPECTED_SENDER", "SIGNATURE_INVALID",
    "TIMESTAMP_INVALID", "PACKET_EXPIRED", "REPLAY_REJECTED", "REPLAY_CAPACITY",
    "DECRYPTION_FAILED", "HANDLER_MISMATCH", "ALERT_CONTENT_INVALID",
})


class AlertReadError(ValueError):
    """Fixed, non-secret diagnostic from the trusted live adapter."""


def _safe_text(value: Any, *, maximum: int, fallback: str = "") -> str:
    if not isinstance(value, str):
        return fallback
    value = value.strip()
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return fallback
    return redact_log_line(value, maximum)


def public_alert(value: Any) -> dict[str, str]:
    """Project one alert onto a fixed public schema and redact inline secrets."""
    if not isinstance(value, dict):
        return {
            "timestamp": "",
            "level": "INFO",
            "origin": "unknown",
            "message": redact_log_line(value, MAX_ALERT_TEXT),
            "event_type": "alert",
            "id": "",
        }

    content = value.get("content") if isinstance(value.get("content"), dict) else value
    message = (
        content.get("formatted_msg")
        or content.get("msg")
        or content.get("message")
        or value.get("details")
        or ""
    )
    level = _safe_text(content.get("level", value.get("level")), maximum=24, fallback="INFO").upper()
    origin = _safe_text(
        content.get("origin", value.get("origin", value.get("agent"))),
        maximum=160,
        fallback="unknown",
    )
    return {
        "timestamp": _safe_text(
            value.get("timestamp", content.get("timestamp")), maximum=64
        ),
        "level": level,
        "origin": origin,
        "message": redact_log_line(message, MAX_ALERT_TEXT),
        "event_type": _safe_text(
            value.get("event_type", "alert"), maximum=64, fallback="alert"
        ),
        "id": _safe_text(content.get("id", value.get("id")), maximum=160),
    }


def public_alert_page(
    deployment_id: str,
    after: int,
    limit: int,
    value: Any,
) -> dict[str, Any]:
    """Validate adapter pagination and rebuild its response from safe fields."""
    expected = {
        "deployment_id",
        "alerts",
        "next_cursor",
        "oldest_cursor",
        "end_cursor",
        "gap",
    }
    if not isinstance(value, dict) or set(value) not in (expected, expected | {"source"}):
        raise RuntimeError("Alert adapter returned an invalid page")
    if value.get("deployment_id") != deployment_id:
        raise RuntimeError("Alert adapter crossed the requested deployment scope")
    alerts = value.get("alerts")
    cursors = (
        value.get("next_cursor"),
        value.get("oldest_cursor"),
        value.get("end_cursor"),
    )
    if (
        not isinstance(alerts, list)
        or len(alerts) > limit
        or any(type(cursor) is not int or cursor < 0 for cursor in cursors)
        or type(value.get("gap")) is not bool
    ):
        raise RuntimeError("Alert adapter returned an invalid page")
    next_cursor, oldest_cursor, end_cursor = cursors
    position = max(after, oldest_cursor)
    if (
        after > end_cursor
        or not oldest_cursor <= position <= next_cursor <= end_cursor
        or next_cursor != position + len(alerts)
        or value["gap"] is not (after < oldest_cursor)
    ):
        raise RuntimeError("Alert adapter returned invalid cursor bounds")
    result = {
        "deployment_id": deployment_id,
        "alerts": [public_alert(alert) for alert in alerts],
        "next_cursor": next_cursor,
        "oldest_cursor": oldest_cursor,
        "end_cursor": end_cursor,
        "gap": value["gap"],
    }
    if "source" in value:
        source = value["source"]
        if (not isinstance(source, dict) or set(source) != {
            "state", "code", "stream_id", "live_only", "may_have_missed", "rejected_packets",
            "received_alerts", "last_rejection"
        } or source.get("state") not in {"connecting", "connected", "reconnecting", "error"}
            or source.get("code") not in {
                "CONNECTING", "AWAITING_ALERTS", "RECEIVING_ALERTS", "PACKET_REJECTED",
                "CONNECTION_FAILED", "SOURCE_CLOSED", "PEER_IDENTITY_FAILED",
                "TRUST_MATERIAL_INVALID", "WORKER_FAILED"
            }
            or not isinstance(source.get("stream_id"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", source["stream_id"])
            or source.get("live_only") is not True
            or type(source.get("may_have_missed")) is not bool
            or type(source.get("rejected_packets")) is not int
            or source["rejected_packets"] < 0
            or type(source.get("received_alerts")) is not int
            or source["received_alerts"] < 0
            or not isinstance(source.get("last_rejection"), str)
            or source["last_rejection"] not in PACKET_REJECTION_REASONS | {""}):
            raise RuntimeError("Alert adapter returned invalid source status")
        result["source"] = dict(source)
    return result


class TerminalAlertBuffer:
    """Trusted ingestion buffer; no client RPC can append, alter, or delete."""

    def __init__(self, capacity: int = MAX_ALERTS_PER_DEPLOYMENT):
        if type(capacity) is not int or capacity < 1 or capacity > MAX_ALERTS_PER_DEPLOYMENT:
            raise ValueError(f"Alert capacity must be from 1 to {MAX_ALERTS_PER_DEPLOYMENT}")
        self._capacity = capacity
        self._buffers: dict[str, list[dict[str, str]]] = defaultdict(list)
        self._starts: dict[str, int] = defaultdict(int)
        self._lock = threading.RLock()

    def append(self, deployment_id: str, alerts: list[Any]) -> None:
        """Accept alerts only from the trusted live-session adapter."""
        if not isinstance(deployment_id, str) or not deployment_id:
            raise ValueError("deployment_id must be a nonempty string")
        if not isinstance(alerts, list) or len(alerts) > MAX_ALERT_PAGE:
            raise ValueError(f"alerts must be a list of at most {MAX_ALERT_PAGE} items")
        projected = [public_alert(alert) for alert in alerts]
        with self._lock:
            buffer = self._buffers[deployment_id]
            buffer.extend(projected)
            dropped = max(0, len(buffer) - self._capacity)
            if dropped:
                del buffer[:dropped]
                self._starts[deployment_id] += dropped

    def read(self, deployment_id: str, after: int, limit: int) -> dict[str, Any]:
        if not isinstance(deployment_id, str) or not deployment_id:
            raise ValueError("deployment_id must be a nonempty string")
        if type(after) is not int or after < 0:
            raise ValueError("after must be a nonnegative integer")
        if type(limit) is not int or not 1 <= limit <= MAX_ALERT_PAGE:
            raise ValueError(f"limit must be from 1 to {MAX_ALERT_PAGE}")
        with self._lock:
            start = self._starts[deployment_id]
            buffer = self._buffers[deployment_id]
            end = start + len(buffer)
            if after > end:
                raise ValueError(
                    "Cursor is beyond this alert stream; reopen the connection or use after=0"
                )
            position = max(after, start)
            items = deepcopy(buffer[position - start : position - start + limit])
        return {
            "deployment_id": deployment_id,
            "alerts": items,
            "next_cursor": position + len(items),
            "oldest_cursor": start,
            "end_cursor": end,
            "gap": after < start,
        }
