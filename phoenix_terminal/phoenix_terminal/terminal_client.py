"""Client-side request identity for the Terminal approval endpoint."""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _descriptor(data_dir):
    path = Path(data_dir) / "terminal-access.json"
    if not path.is_file():
        raise RuntimeError(
            "Phoenix AI access is not open. Ask the operator to open the vault "
            "in AI Mode and choose Open AI access with this client data directory. "
            "For the legacy independent console, use 'phoenixctl terminal open'."
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
        previous_secret = None
        if self.path.exists():
            current = self.load()
            previous_secret = current["client_secret"]
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
            # Renew approval using the same enrolled identity. A fresh request
            # ID is not a new vault credential, and cannot bypass revocation.
            "client_secret": previous_secret or secrets.token_urlsafe(32),
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

    def request_and_wait(self, client_label, *, wait_seconds=45):
        """One bounded MCP call; only the operator broker can grant access.

        CLI request remains immediate. Poll privately with the same identity,
        never create a second request or treat elapsed time as a decision.
        """
        if type(wait_seconds) is not int or not 0 <= wait_seconds <= 45:
            raise ValueError("Approval wait must be an integer from 0 to 45 seconds")
        deadline = time.monotonic() + wait_seconds
        result = self.request(client_label)
        if result.get("state") == "pending" and wait_seconds:
            record = self.load()
            if record["request_id"] != result.get("request_id"):
                raise RuntimeError("Terminal request identity changed; check approval status")
            while result.get("state") == "pending":
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(1, remaining))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if self.load() != record:
                    raise RuntimeError("Terminal request identity changed; check approval status")
                result = call_terminal(self.data_dir, "connection.status", {
                    "request_id": record["request_id"],
                    "client_secret": record["client_secret"],
                }, timeout=min(10, remaining))
                if result.get("request_id") != record["request_id"]:
                    raise RuntimeError("Terminal approval response identity did not match")
        state = result.get("state")
        return {**result, "approval_wait_timed_out": state == "pending" and wait_seconds > 0,
                "next_step": (
                    "Use the approved resources and tool_calls in this result directly; no extra status call or typed confirmation is needed."
                    if state == "approved" else
                    "Still pending; no access granted. Wait for the operator, then check status once. Do not submit another request or loop on status."
                    if state == "pending" else
                    "Access is not approved. Stop dependent operations; do not automatically request again."
                )}

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
            "deployment_id": deployment_id, **fields}, timeout=70 if method == "sessions.open" else 60 if method in {
                "swarms.list", "agents.list", "logs.read", "swarm.inspect", "sessions.list"} else 10)

    def list_swarms(self, deployment_id):
        return self._operation("swarms.list", deployment_id)

    def list_agents(self, deployment_id):
        return self._operation("agents.list", deployment_id)

    def read_logs(self, deployment_id, agent_id):
        return self._operation("logs.read", deployment_id, agent_id=agent_id)

    def inspect_swarm(self, deployment_id):
        return self._operation("swarm.inspect", deployment_id)

    def list_sessions(self, deployment_id):
        return self._operation("sessions.list", deployment_id)

    def open_session(self, deployment_id):
        return self._operation("sessions.open", deployment_id)

    def launch_railgun(self, deployment_id, operation_id):
        return self._operation("railgun.launch", deployment_id, operation_id=operation_id)

    def railgun_status(self, deployment_id, operation_id):
        return self._operation("railgun.status", deployment_id, operation_id=operation_id)

    def clear(self):
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"Could not remove Terminal client identity: {exc}") from exc
