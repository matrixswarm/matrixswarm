"""Authenticated, non-blocking client for MatrixSwarm MCP Reflex agents."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Mapping
from typing import Any

from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import (
    IdentityObject,
)


class McpReflexClientError(RuntimeError):
    """An MCP Reflex request could not be created or delivered."""


class McpReflexClientMixin:
    """Send signed requests directly to MCP Reflex and correlate its replies.

    The caller resolves the advertised service endpoint, then uses
    ``pass_packet`` directly.  Matrix is not used as a request proxy, so the
    caller's verified agent identity remains authoritative at the airlock.
    """

    _mcp_roles = {
        "list_tools": "hive.mcp.tools",
        "call_tool": "hive.mcp.call_tool",
    }

    def init_mcp_reflex_client(
        self, *, max_pending: int = 16, request_timeout_sec: int = 60
    ) -> None:
        if isinstance(max_pending, bool) or not 1 <= max_pending <= 128:
            raise McpReflexClientError("max_pending must be from 1 to 128")
        if (
            isinstance(request_timeout_sec, bool)
            or not 1 <= request_timeout_sec <= 600
        ):
            raise McpReflexClientError(
                "request_timeout_sec must be from 1 to 600"
            )
        self._mcp_client_max_pending = max_pending
        self._mcp_client_timeout = request_timeout_sec
        self._mcp_client_pending: dict[str, dict[str, Any]] = {}
        self._mcp_client_lock = threading.RLock()

    def request_mcp_tools(
        self,
        server_id: str,
        *,
        request_id: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> str:
        return self._send_mcp_reflex_request(
            "list_tools",
            {"server_id": self._mcp_text(server_id, "server_id")},
            request_id=request_id,
            context=context,
        )

    def request_mcp_tool_call(
        self,
        server_id: str,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        request_id: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> str:
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, Mapping):
            raise McpReflexClientError("arguments must be a mapping")
        return self._send_mcp_reflex_request(
            "call_tool",
            {
                "server_id": self._mcp_text(server_id, "server_id"),
                "tool_name": self._mcp_text(tool_name, "tool_name"),
                "arguments": dict(arguments),
            },
            request_id=request_id,
            context=context,
        )

    def _send_mcp_reflex_request(
        self,
        operation: str,
        payload: dict[str, Any],
        *,
        request_id: str | None,
        context: Mapping[str, Any] | None,
    ) -> str:
        if not hasattr(self, "_mcp_client_pending"):
            raise McpReflexClientError("call init_mcp_reflex_client() first")
        role = self._mcp_roles[operation]
        # Ambiguous airlocks fail closed. The signed directive must advertise
        # exactly one endpoint for each MCP operation role.
        endpoints = list(self.get_nodes_by_role(role))
        if len(endpoints) != 1:
            raise McpReflexClientError(
                f"exactly one MCP Reflex endpoint is required for {role}"
            )
        endpoint = endpoints[0]
        target_uid = endpoint.get_universal_id()
        handler = endpoint.get_handler()
        if not isinstance(target_uid, str) or not target_uid:
            raise McpReflexClientError("MCP Reflex endpoint UID is missing")
        if not isinstance(handler, str) or not handler:
            raise McpReflexClientError("MCP Reflex endpoint handler is missing")

        request_id = request_id or secrets.token_hex(16)
        request_id = self._mcp_text(request_id, "request_id")
        if len(request_id) > 128:
            raise McpReflexClientError("request_id exceeds 128 characters")
        if context is not None and not isinstance(context, Mapping):
            raise McpReflexClientError("context must be a mapping")

        pending = {
            "operation": operation,
            "reflex_uid": target_uid,
            "created": time.monotonic(),
            "context": dict(context or {}),
        }
        with self._mcp_client_lock:
            if len(self._mcp_client_pending) >= self._mcp_client_max_pending:
                raise McpReflexClientError("MCP Reflex client queue is full")
            if request_id in self._mcp_client_pending:
                raise McpReflexClientError("request_id is already pending")
            self._mcp_client_pending[request_id] = pending

        try:
            packet = self.get_delivery_packet("standard.command.packet")
            content_packet = self.get_delivery_packet(
                "standard.general.json.packet"
            )
            content_packet.set_data({"request_id": request_id, **payload})
            packet.set_data({"handler": handler})
            packet.set_packet(content_packet, "content")
            delivered = self.pass_packet(packet, target_uid)
        except Exception as exc:
            with self._mcp_client_lock:
                self._mcp_client_pending.pop(request_id, None)
            raise McpReflexClientError(
                "MCP Reflex request delivery failed"
            ) from exc
        if not delivered:
            with self._mcp_client_lock:
                self._mcp_client_pending.pop(request_id, None)
            raise McpReflexClientError("MCP Reflex request delivery failed")
        self._mcp_client_audit(
            f"request delivered operation={operation} "
            f"request={request_id[:12]} target={target_uid}"
        )
        return request_id

    def cmd_mcp_result(
        self, content: Any, _packet: Any, identity: IdentityObject | None = None
    ) -> None:
        if not isinstance(content, Mapping):
            self._mcp_client_audit("callback rejected: content is not a mapping", "WARN")
            return
        request_id = content.get("request_id")
        if not isinstance(request_id, str):
            self._mcp_client_audit("callback rejected: request ID is missing", "WARN")
            return
        with self._mcp_client_lock:
            pending = self._mcp_client_pending.get(request_id)
            if pending is None:
                self._mcp_client_audit(
                    f"callback rejected: unknown request={request_id[:12]}",
                    "WARN",
                )
                return
            if not isinstance(identity, IdentityObject) or not identity.has_verified_identity():
                self._mcp_client_audit(
                    f"callback rejected: unverified identity request={request_id[:12]}",
                    "WARN",
                )
                return
            sender_uid = identity.get_sender_uid()
            if sender_uid != pending["reflex_uid"]:
                self._mcp_client_audit(
                    f"callback rejected: unexpected sender request={request_id[:12]}",
                    "WARN",
                )
                return
            if content.get("operation") != pending["operation"]:
                self._mcp_client_audit(
                    f"callback rejected: operation mismatch request={request_id[:12]}",
                    "WARN",
                )
                return
            self._mcp_client_pending.pop(request_id, None)
        self._mcp_client_audit(
            f"verified callback accepted operation={pending['operation']} "
            f"request={request_id[:12]}"
        )
        callback = getattr(self, "on_mcp_result", None)
        if callable(callback):
            callback(dict(content), pending)

    def expire_mcp_requests(self) -> list[str]:
        if not hasattr(self, "_mcp_client_pending"):
            return []
        now = time.monotonic()
        with self._mcp_client_lock:
            expired = [
                request_id
                for request_id, pending in self._mcp_client_pending.items()
                if now - pending["created"] >= self._mcp_client_timeout
            ]
            entries = [
                (request_id, self._mcp_client_pending.pop(request_id))
                for request_id in expired
            ]
        callback = getattr(self, "on_mcp_timeout", None)
        if callable(callback):
            for request_id, pending in entries:
                callback(request_id, pending)
        return expired

    def _mcp_client_audit(self, message: str, level: str = "INFO") -> None:
        """Emit bounded local diagnostics without exposing tool arguments."""
        logger = getattr(self, "log", None)
        if not callable(logger):
            return
        try:
            logger(f"[MCP-CLIENT] {message[:512]}", level=level)
        except TypeError:
            logger(f"[MCP-CLIENT] {message[:512]}")

    @staticmethod
    def _mcp_text(value: Any, field: str) -> str:
        if (
            not isinstance(value, str)
            or not value.strip()
            or any(control in value for control in ("\x00", "\r", "\n"))
        ):
            raise McpReflexClientError(f"{field} must be a non-empty string")
        return value.strip()
