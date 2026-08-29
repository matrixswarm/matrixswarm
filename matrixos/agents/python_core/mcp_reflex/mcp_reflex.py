"""Signed MatrixSwarm ingress for approved external MCP tools."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

from core.python_core.boot_agent import BootAgent
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import (
    IdentityObject,
)
from core.python_core.mixin.mcp_reflex_policy import (
    PolicyError, allowed_tools, authorize_tool, server_config,
)


REPLY_HANDLER = "cmd_mcp_result"
MAX_REQUEST_ID_LENGTH = 128
MAX_TOOL_NAME_LENGTH = 128
MAX_REQUEST_BYTES_DEFAULT = 262_144
MAX_RESULT_BYTES_DEFAULT = 262_144
WORKER_SHA256 = "036609ad8cf22ef4bbc691608a2bf18eb7003ffbc861a840407a65d7f80c8737"


class Agent(BootAgent):
    """Run MCP requests without exposing MatrixSwarm internals to MCP code."""

    def __init__(self) -> None:
        super().__init__()
        self.config = self.tree_node.get("config", {})
        self._max_workers = self._positive_int("max_workers", 2, 16)
        self._max_pending = self._positive_int("max_pending", 8, 64)
        self._worker_timeout = self._positive_int("worker_timeout_sec", 45, 360)
        self._max_request_bytes = self._positive_int(
            "max_request_bytes", MAX_REQUEST_BYTES_DEFAULT, 2_097_152
        )
        self._max_result_bytes = self._positive_int(
            "max_result_bytes", MAX_RESULT_BYTES_DEFAULT, 2_097_152
        )
        self._replay_window = self._positive_int(
            "replay_window_sec", 300, 86_400
        )
        self._max_completed = self._positive_int(
            "max_completed_requests", 4_096, 65_536
        )
        self._pending = threading.BoundedSemaphore(self._max_pending)
        self._inflight: set[tuple[str, str]] = set()
        self._completed: dict[tuple[str, str], float] = {}
        self._inflight_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers, thread_name_prefix="mcp-reflex"
        )

    def _positive_int(self, name: str, default: int, maximum: int) -> int:
        value = self.config.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            return default
        return value

    @staticmethod
    def _verified_sender(identity: Any) -> str | None:
        """Require authentication even in plaintext development mode."""
        if not isinstance(identity, IdentityObject):
            return None
        if not identity.has_verified_identity():
            return None
        sender_uid = identity.get_sender_uid()
        if not isinstance(sender_uid, str) or not sender_uid:
            return None
        return sender_uid

    @staticmethod
    def _request_id(content: Mapping[str, Any]) -> str:
        value = content.get("request_id")
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_REQUEST_ID_LENGTH:
            raise ValueError("request_id must be a non-empty string up to 128 characters")
        return value.strip()

    @staticmethod
    def _string_field(content: Mapping[str, Any], field: str) -> str:
        value = content.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_TOOL_NAME_LENGTH:
            raise ValueError(f"{field} must be a non-empty string up to 128 characters")
        return value.strip()

    def _send_result(
        self, recipient_uid: str, request_id: str, operation: str, **payload: Any
    ) -> bool:
        inner = self.get_delivery_packet("standard.general.json.packet")
        inner.set_data({"request_id": request_id, "operation": operation, **payload})
        outer = self.get_delivery_packet("standard.command.packet")
        outer.set_data({"handler": REPLY_HANDLER})
        outer.set_packet(inner, "content")
        # Preserve the completed callback payload. The generic packet
        # auto-fill behavior would otherwise overwrite it with the outer
        # command packet's empty ``content`` mapping at serialization time.
        outer.set_auto_fill_sub_packet(False)
        delivered = bool(self.pass_packet(outer, recipient_uid))
        status = payload.get("status", "unknown")
        self._audit(
            "CALLBACK" if delivered else "CALLBACK-FAIL",
            recipient_uid,
            request_id,
            operation,
            f"status={status}",
            level="INFO" if delivered else "ERROR",
        )
        return delivered

    def _deny(self, sender_uid: str | None, content: Mapping[str, Any], operation: str, error: str) -> None:
        request_id = content.get("request_id")
        if sender_uid and isinstance(request_id, str) and request_id.strip() and len(request_id) <= MAX_REQUEST_ID_LENGTH:
            self._audit(
                "DENY", sender_uid, request_id.strip(), operation, error,
                level="WARN",
            )
            self._send_result(sender_uid, request_id.strip(), operation, status="denied", error=error)

    def _audit(
        self,
        event: str,
        sender_uid: str | None,
        request_id: str | None,
        operation: str,
        detail: str = "",
        *,
        level: str = "INFO",
    ) -> None:
        """Log bounded transaction metadata; never log arguments or server env."""
        sender = sender_uid if isinstance(sender_uid, str) else "unverified"
        request = request_id[:12] if isinstance(request_id, str) else "unknown"
        safe_detail = str(detail).replace("\r", " ").replace("\n", " ")[:256]
        self.log(
            f"[MCP-AIRLOCK][{event}] sender={sender[:128]} "
            f"request={request} operation={operation} {safe_detail}".rstrip(),
            level=level,
        )

    def cmd_mcp_list_tools(self, content: Any, _packet: Any, identity: Any) -> None:
        self._dispatch_request("list_tools", content, identity)

    def cmd_mcp_call_tool(self, content: Any, _packet: Any, identity: Any) -> None:
        self._dispatch_request("call_tool", content, identity)

    def _dispatch_request(self, operation: str, content: Any, identity: Any) -> None:
        """Instrument the authenticated handler boundary without logging payloads."""
        request_id = content.get("request_id") if isinstance(content, Mapping) else None
        request = request_id[:12] if isinstance(request_id, str) else "unknown"
        identity_type_match = isinstance(identity, IdentityObject)
        identity_verified = False
        uid_present = False
        if identity_type_match:
            try:
                identity_verified = bool(identity.has_verified_identity())
                sender_uid = identity.get_sender_uid()
                uid_present = isinstance(sender_uid, str) and bool(sender_uid)
            except Exception:
                # Identity inspection is diagnostic only. The authoritative
                # fail-closed check remains in ``_verified_sender``.
                pass
        self.log(
            f"[MCP-AIRLOCK][HANDLER-ENTER] request={request} "
            f"operation={operation} identity_type_match={identity_type_match} "
            f"verified={identity_verified} uid_present={uid_present}"
        )
        try:
            self._handle_request(operation, content, identity)
        finally:
            self.log(
                f"[MCP-AIRLOCK][HANDLER-EXIT] request={request} "
                f"operation={operation}"
            )

    def _handle_request(self, operation: str, content: Any, identity: Any) -> None:
        sender_uid = self._verified_sender(identity)
        if not isinstance(content, Mapping):
            self._audit("DROP", sender_uid, None, operation, "malformed content", level="WARN")
            self._deny(sender_uid, {}, operation, "content must be a mapping")
            return
        if sender_uid is None:
            self._audit(
                "DROP", None, content.get("request_id"), operation,
                "unverified sender", level="WARN",
            )
            return
        try:
            request_id = self._request_id(content)
            server_id = self._string_field(content, "server_id")
            if operation == "call_tool":
                tool_name = self._string_field(content, "tool_name")
                arguments = content.get("arguments", {})
                if not isinstance(arguments, Mapping):
                    raise ValueError("arguments must be a mapping")
                server = authorize_tool(self.config, sender_uid, server_id, tool_name)
                permitted_tools = {tool_name}
            else:
                server = server_config(self.config, server_id)
                permitted_tools = allowed_tools(self.config, sender_uid, server_id)
        except (ValueError, PolicyError) as exc:
            self._deny(sender_uid, content, operation, str(exc))
            return
        self._audit(
            "ACCEPT", sender_uid, request_id, operation,
            f"server={server_id} tools={','.join(sorted(permitted_tools))}",
        )
        key = (sender_uid, request_id)
        with self._inflight_lock:
            now = time.monotonic()
            self._completed = {
                completed_key: expires_at
                for completed_key, expires_at in self._completed.items()
                if expires_at > now
            }
            if key in self._inflight:
                self._send_result(sender_uid, request_id, operation, status="denied", error="duplicate request_id is already in flight")
                return
            if key in self._completed:
                self._send_result(sender_uid, request_id, operation, status="denied", error="request_id was already completed")
                return
            if not self._pending.acquire(blocking=False):
                self._send_result(sender_uid, request_id, operation, status="busy", error="mcp_reflex queue is full")
                return
            self._inflight.add(key)
        payload: dict[str, Any] = {
            "operation": operation, "server": server,
            "permitted_tools": sorted(permitted_tools),
        }
        if operation == "call_tool":
            payload["tool_name"] = tool_name
            payload["arguments"] = dict(arguments)
        try:
            self._executor.submit(
                self._run_and_reply, sender_uid, request_id, payload
            )
        except Exception as exc:
            with self._inflight_lock:
                self._inflight.discard(key)
                self._pending.release()
            self._audit(
                "WORKER-QUEUE-FAIL", sender_uid, request_id, operation,
                type(exc).__name__, level="ERROR",
            )
            self._send_result(
                sender_uid, request_id, operation, status="error",
                error="worker could not be scheduled",
            )

    def _worker_command(self) -> list[str]:
        source_root = self.path_resolution.get("agent_path")
        if not isinstance(source_root, str):
            raise RuntimeError("worker source path is unavailable")
        source = Path(source_root) / "mcp_reflex" / "worker" / "mcp_stdio_worker.py"
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != WORKER_SHA256:
            raise RuntimeError("MCP worker hash does not match the signed bridge source")

        sandbox = self.config.get("sandbox", {})
        if not isinstance(sandbox, Mapping) or sandbox.get("enabled") is not True:
            raise RuntimeError("MCP sandbox is required")
        launcher = sandbox.get(
            "launcher", "/usr/local/libexec/matrix-mcp-launch"
        )
        if (
            not isinstance(launcher, str)
            or not launcher.startswith("/")
            or launcher != "/usr/local/libexec/matrix-mcp-launch"
        ):
            raise RuntimeError("MCP sandbox launcher is invalid")
        if os.name != "posix" or not Path(launcher).is_file():
            raise RuntimeError("MCP sandbox launcher is not installed")
        return ["/usr/bin/sudo", "-n", launcher]

    def _run_and_reply(self, sender_uid: str, request_id: str, payload: dict[str, Any]) -> None:
        operation = payload["operation"]
        self._audit("WORKER-START", sender_uid, request_id, operation)
        try:
            result = self._invoke_worker(payload)
            self._audit(
                "WORKER-END", sender_uid, request_id, operation,
                f"ok={bool(result.get('ok'))}",
            )
            self._send_result(sender_uid, request_id, operation, status="ok" if result.get("ok") else "error", result=result.get("result"), error=result.get("error"))
        except Exception as exc:
            self._audit(
                "WORKER-FAIL", sender_uid, request_id, operation,
                type(exc).__name__, level="ERROR",
            )
            self._send_result(sender_uid, request_id, operation, status="error", error=f"worker failed: {type(exc).__name__}")
        finally:
            with self._inflight_lock:
                self._inflight.discard((sender_uid, request_id))
                self._completed[(sender_uid, request_id)] = (
                    time.monotonic() + self._replay_window
                )
                while len(self._completed) > self._max_completed:
                    self._completed.pop(next(iter(self._completed)))
                self._pending.release()

    def _invoke_worker(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(request) > self._max_request_bytes:
            raise RuntimeError("worker request exceeds configured limit")
        worker_env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR") if key in os.environ}
        # A file-backed sink prevents an untrusted worker from forcing an
        # unbounded bytes object into the Matrix process. The launcher also
        # applies RLIMIT_FSIZE as a second, child-side ceiling.
        with tempfile.TemporaryFile(mode="w+b") as output:
            completed = subprocess.run(
                self._worker_command(), input=request + b"\n", stdout=output,
                stderr=subprocess.DEVNULL, env=worker_env,
                timeout=self._worker_timeout, check=False,
            )
            output.seek(0)
            response_bytes = output.read(self._max_result_bytes + 1)
        if len(response_bytes) > self._max_result_bytes:
            raise RuntimeError("worker result exceeds configured limit")
        if completed.returncode != 0:
            raise RuntimeError("worker exited unsuccessfully")
        response = json.loads(response_bytes.decode("utf-8"))
        if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
            raise RuntimeError("worker returned invalid JSON")
        return response


if __name__ == "__main__":
    agent = Agent()
    agent.boot()
