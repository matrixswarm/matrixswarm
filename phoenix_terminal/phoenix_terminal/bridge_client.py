"""Client for the authenticated bridge hosted inside Phoenix Cockpit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def call_bridge(data_dir: Path, method: str, params: dict[str, Any] | None = None, timeout: float = 130) -> dict[str, Any]:
    connection_path = data_dir / "bridge.json"
    if not connection_path.exists():
        raise RuntimeError("Phoenix bridge is not running; launch Phoenix with 'phoenixctl launch'")
    connection = json.loads(connection_path.read_text(encoding="utf-8"))
    host = connection.get("host")
    port = connection.get("port")
    token = connection.get("token")
    if host != "127.0.0.1" or not isinstance(port, int) or not isinstance(token, str):
        raise RuntimeError("Phoenix bridge connection file is invalid")
    payload = json.dumps({"method": method, "params": params or {}}).encode("utf-8")
    request = Request(
        f"http://127.0.0.1:{port}/rpc",
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310: loopback endpoint is validated above
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        result = json.loads(exc.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"Phoenix bridge is unreachable: {exc.reason}") from exc
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error", "bridge request failed")))
    return result.get("result", {})
