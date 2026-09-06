"""Redaction helpers for the Phoenix/LLM trust boundary."""

from __future__ import annotations

import json
import re
from typing import Any


_SECRET_KEY = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|private[_-]?key|privkey|credential|authorization)",
    re.IGNORECASE,
)
_INLINE_SECRET = re.compile(
    r'''(?ix)
    \b(
        password|passwd|passphrase|token|secret|authorization|credentials?|
        api[_\s-]?key|access[_\s-]?key|private[_\s-]?key|privkey|
        aes[_\s-]?key|signing[_\s-]?key|session[_\s-]?key
    )\b["']?\s*[:=]\s*["']?([^\s,;}"']+)
    '''
)
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
    re.DOTALL,
)
_URL_CREDENTIALS = re.compile(r"(?i)(https?://)[^/@\s]+@")


def redact_value(value: Any) -> Any:
    """Recursively remove secret-shaped fields from an object."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    return value


def redact_log_line(line: Any, max_chars: int = 8000) -> str:
    if isinstance(line, str):
        text = line
    else:
        text = json.dumps(redact_value(line), ensure_ascii=False, default=str)
    text = _PEM_PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", text)
    text = _INLINE_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", text)
    return text[:max_chars]


def public_deployment(deployment_id: str, deployment: dict[str, Any]) -> dict[str, Any]:
    """Return deployment identity without connections, certificates, or config."""
    agents = deployment.get("agents") if isinstance(deployment, dict) else []
    return {
        "id": deployment_id,
        "label": deployment.get("label", deployment_id),
        "name": deployment.get("name", deployment_id),
        "agent_count": len(agents) if isinstance(agents, list) else 0,
    }


def public_agent(agent: dict[str, Any]) -> dict[str, Any]:
    """Expose agent-tree identity and routing role, never connection material."""
    connection = agent.get("connection") if isinstance(agent.get("connection"), dict) else {}
    return {
        "universal_id": agent.get("universal_id"),
        "name": agent.get("name"),
        "app": agent.get("app"),
        "parent": agent.get("parent"),
        "channel": connection.get("channel"),
        "protocol": connection.get("proto"),
    }


def public_agent_tree(tree: Any) -> list[dict[str, Any]]:
    """Flatten a rendered Phoenix agent tree into redacted identities."""
    found: dict[str, dict[str, Any]] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            universal_id = value.get("universal_id")
            if isinstance(universal_id, str) and universal_id:
                found[universal_id] = public_agent(value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(tree)
    return list(found.values())
