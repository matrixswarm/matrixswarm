"""Authenticated loopback JSON-RPC transport for the in-process bridge."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable


Dispatch = Callable[[str, dict[str, Any]], dict[str, Any]]


class BridgeServer:
    def __init__(self, dispatch: Dispatch, data_dir: Path):
        self._dispatch = dispatch
        self._data_dir = data_dir
        self._token = secrets.token_urlsafe(32)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def connection_path(self) -> Path:
        return self._data_dir / "bridge.json"

    def start(self) -> dict[str, Any]:
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "PhoenixBridge/0.1"

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _json(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
                if self.path != "/rpc":
                    self._json(404, {"ok": False, "error": "not_found"})
                    return
                supplied = self.headers.get("Authorization", "")
                expected = f"Bearer {bridge._token}"
                if not hmac.compare_digest(supplied, expected):
                    self._json(401, {"ok": False, "error": "unauthorized"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 65536:
                        raise ValueError("request size is invalid")
                    request = json.loads(self.rfile.read(length).decode("utf-8"))
                    method = request.get("method")
                    params = request.get("params", {})
                    if not isinstance(method, str) or not isinstance(params, dict):
                        raise ValueError("method must be a string and params must be an object")
                    result = bridge._dispatch(method, params)
                    self._json(200, {"ok": True, "result": result})
                except Exception as exc:
                    self._json(400, {"ok": False, "error": str(exc)})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="phoenix-bridge", daemon=True)
        self._thread.start()

        self._data_dir.mkdir(parents=True, exist_ok=True)
        connection = {
            "version": 1,
            "host": "127.0.0.1",
            "port": self._server.server_port,
            "token": self._token,
            "pid": os.getpid(),
        }
        self.connection_path.write_text(json.dumps(connection, indent=2) + "\n", encoding="utf-8")
        try:
            self.connection_path.chmod(0o600)
        except OSError:
            pass
        return {key: value for key, value in connection.items() if key != "token"}

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        try:
            if self.connection_path.exists():
                current = json.loads(self.connection_path.read_text(encoding="utf-8"))
                if current.get("pid") == os.getpid():
                    self.connection_path.unlink()
        except (OSError, json.JSONDecodeError):
            pass
