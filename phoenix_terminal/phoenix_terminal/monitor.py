"""Small, dependency-free, opt-in endpoint availability monitor."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_CONFIG = {"version": 1, "targets": []}


@dataclass(frozen=True)
class CheckResult:
    name: str
    url: str
    ok: bool
    status: int | None
    latency_ms: int | None
    error: str | None
    checked_at: int


def config_path(data_dir: Path) -> Path:
    return data_dir / "monitors.json"


def load_config(data_dir: Path) -> dict[str, Any]:
    path = config_path(data_dir)
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(data_dir: Path, config: dict[str, Any]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    config_path(data_dir).write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def add_target(data_dir: Path, name: str, url: str, expected_status: int) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("URL must be an absolute http:// or https:// endpoint")
    config = load_config(data_dir)
    if any(target["name"] == name for target in config["targets"]):
        raise ValueError(f"A monitor named '{name}' already exists")
    config["targets"].append({"name": name, "url": url, "expected_status": expected_status})
    save_config(data_dir, config)


def check_target(target: dict[str, Any], timeout_seconds: float = 10.0) -> CheckResult:
    started = time.perf_counter()
    status: int | None = None
    error: str | None = None
    try:
        request = Request(target["url"], headers={"User-Agent": "phoenix-terminal/0.1"}, method="GET")
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310: URL is explicitly operator-configured
            status = response.status
    except HTTPError as exc:
        status = exc.code
    except (URLError, TimeoutError, OSError) as exc:
        error = str(exc.reason if isinstance(exc, URLError) else exc)
    latency_ms = round((time.perf_counter() - started) * 1000)
    return CheckResult(
        name=target["name"], url=redact_url(target["url"]),
        ok=status == target["expected_status"], status=status,
        latency_ms=latency_ms, error=error, checked_at=int(time.time()),
    )


def record_results(data_dir: Path, results: list[CheckResult]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / "monitor-history.jsonl").open("a", encoding="utf-8") as stream:
        for result in results:
            stream.write(json.dumps(asdict(result)) + "\n")
