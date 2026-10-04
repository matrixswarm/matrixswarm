"""Client-side request identity for the Terminal approval endpoint."""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _descriptor(data_dir):
    path = Path(data_dir) / "terminal-access.json"
    if not path.is_file():
        raise RuntimeError(
            "Phoenix Terminal access is not open. Ask the operator to run "
            "'phoenixctl terminal open'."
        )
    try:
        connection = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Terminal access descriptor is invalid") from exc
    if (
        connection.get("host") != "127.0.0.1"
        or type(connection.get("port")) is not int
        or not isinstance(connection.get("token"), str)
    ):
        raise RuntimeError("Terminal access descriptor is invalid")
    return connection


def call_terminal(data_dir, method, params=None, timeout=10):
    connection = _descriptor(data_dir)
    payload = json.dumps({"method": method, "params": params or {}}).encode("utf-8")
    request = Request(
        f"http://127.0.0.1:{connection['port']}/rpc",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {connection['token']}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310: fixed loopback host
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        result = json.loads(exc.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"Terminal access endpoint is unreachable: {exc.reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"Terminal access request was interrupted: {exc}") from exc
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error", "Terminal access request failed")))
    value = result.get("result", {})
    if not isinstance(value, dict):
        raise RuntimeError("Terminal access endpoint returned an invalid response")
    return value


class TerminalClientIdentity:
    """Persist one opaque local client secret without printing it."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "terminal-client.json"

    def _write(self, record):
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".terminal-client-", dir=self.data_dir)
        try:
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(record, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise

    def load(self):
        if not self.path.is_file():
            raise RuntimeError("No Terminal connection request exists for this data directory")
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Terminal client identity is invalid") from exc
        if not isinstance(value, dict) or set(value) != {
            "request_id",
            "client_label",
            "client_secret",
        }:
            raise RuntimeError("Terminal client identity is invalid")
        return value

    def request(self, client_label):
        if self.path.exists():
            current = self.load()
            try:
                status = call_terminal(
                    self.data_dir,
                    "connection.status",
                    {
                        "request_id": current["request_id"],
                        "client_secret": current["client_secret"],
                    },
                )
            except RuntimeError as exc:
                if "identity did not match" not in str(exc):
                    raise
                self.clear()
                status = {"state": "stale"}
            if status.get("state") in {"pending", "approved"}:
                return status
            self.clear()
        record = {
            "request_id": secrets.token_urlsafe(18),
            "client_label": client_label,
            "client_secret": secrets.token_urlsafe(32),
        }
        result = call_terminal(self.data_dir, "connection.request", record)
        self._write(record)
        return result

    def status(self):
        record = self.load()
        return call_terminal(
            self.data_dir,
            "connection.status",
            {
                "request_id": record["request_id"],
                "client_secret": record["client_secret"],
            },
        )

    def disconnect(self):
        record = self.load()
        try:
            return call_terminal(
                self.data_dir,
                "connection.disconnect",
                {
                    "request_id": record["request_id"],
                    "client_secret": record["client_secret"],
                },
            )
        finally:
            self.clear()

    def read_alerts(self, deployment_id, *, after=0, limit=100, stream_id=None):
        record = self.load()
        params = {
            "request_id": record["request_id"], "client_secret": record["client_secret"],
            "deployment_id": deployment_id, "after": after, "limit": limit,
        }
        if stream_id is not None:
            params["stream_id"] = stream_id
        return call_terminal(
            self.data_dir,
            "alerts.read",
            params,
        )

    def _operation(self, method, deployment_id, **fields):
        record = self.load()
        return call_terminal(self.data_dir, method, {
            "request_id": record["request_id"], "client_secret": record["client_secret"],
            "deployment_id": deployment_id, **fields}, timeout=60 if method == "swarms.list" else 10)

    def list_swarms(self, deployment_id):
        return self._operation("swarms.list", deployment_id)

    def launch_railgun(self, deployment_id, operation_id):
        return self._operation("railgun.launch", deployment_id, operation_id=operation_id)

    def railgun_status(self, deployment_id, operation_id):
        return self._operation("railgun.status", deployment_id, operation_id=operation_id)

    def clear(self):
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Could not remove Terminal client identity: {exc}") from exc
