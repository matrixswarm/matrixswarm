"""Session-process shim that forwards LLM log requests through Phoenix buses."""

from __future__ import annotations

import time
import threading
from typing import Any


class SerializedConnection:
    """Serialize writers sharing one multiprocessing Connection.

    Phoenix emits heartbeats from the Qt session while inbound agent callbacks can
    arrive on connector threads. ``multiprocessing.Connection`` supports duplex
    traffic but explicitly does not support concurrent ``send_bytes`` calls.
    Wrapping the connection once, before Phoenix receives it, protects every
    existing and bridge-added sender without changing Phoenix's source tree.
    """

    def __init__(self, connection: object):
        self._connection = connection
        self._send_lock = threading.Lock()

    def send(self, value: object) -> None:
        with self._send_lock:
            self._connection.send(value)

    def send_bytes(self, *args: Any, **kwargs: Any) -> None:
        with self._send_lock:
            self._connection.send_bytes(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def bridged_run_session(
    session_id: str,
    conn: object,
    debug_output: bool = False,
) -> None:
    """Run the original Phoenix session with a narrow bridge pipe extension.

    This is a multiprocessing target and must remain importable at module scope.
    Phoenix's source is not patched on disk.
    """
    from matrix_gui.core import session_window as session_module
    from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet

    original_window = session_module.SessionWindow

    class BridgeSessionWindow(original_window):
        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, **kwargs)
            self._bridge_restart_ids = set()
            self._bridge_log_tokens: dict[str, dict[str, Any]] = {}
            self.bus.on("inbound.verified.agent_log_view.update", self._bridge_on_log_update)

        def _poll_conn(self) -> None:
            if not self.conn:
                return
            try:
                while self.conn.poll():
                    message = self.conn.recv()
                    message_type = message.get("type") if isinstance(message, dict) else None
                    if message_type == "force_close":
                        print(f"[SESSION] Received external close for {self.session_id}")
                        self._handle_external_close()
                    elif message_type == "bridge.fetch_logs":
                        self._bridge_fetch_logs(message)
                    elif message_type == "bridge.revoke":
                        self._bridge_log_tokens.clear()
                    elif message_type == "bridge.restart":
                        self._bridge_restart(message)
                    elif message_type == "bridge.agent_tree":
                        self._bridge_send_agent_tree()
            except (EOFError, OSError):
                print(f"[SESSION][PIPE] Lost pipe for {self.session_id}")
                self._pipe_timer.stop()

        def _bridge_restart(self, message):
            from matrix_gui.core.class_lib.services.agent_actions import restart_agent
            request_id = message.get("request_id")
            agent_id = message.get("agent_id")
            from .deployment_view import agent_nodes
            known = {a.get("universal_id") for a in agent_nodes(self.deployment.get("agents", []))}
            state = "failed"
            try:
                if (message.get("session_id") != self.session_id or agent_id not in known
                        or not isinstance(request_id, str) or not request_id
                        or request_id in self._bridge_restart_ids or len(self._bridge_restart_ids) >= 256):
                    raise ValueError("Invalid or duplicate terminal restart.")
                self._bridge_restart_ids.add(request_id)
                restart_agent(self.bus, self.session_id, agent_id, False, request_id)
                state = "sent"
            except Exception:
                pass
            self.conn.send({"type": "bridge.action", "session_id": self.session_id,
                            "request_id": request_id, "state": state})

        def _bridge_fetch_logs(self, message: dict[str, Any]) -> None:
            subscription_id = str(message.get("subscription_id", ""))
            agent_id = str(message.get("agent_id", ""))
            follow = bool(message.get("follow", True))
            if not subscription_id or not agent_id:
                self.conn.send({
                    "type": "bridge.log.error",
                    "subscription_id": subscription_id,
                    "error": "subscription_id and agent_id are required",
                })
                return
            from .deployment_view import agent_nodes
            known_agents = {
                str(agent.get("universal_id"))
                for agent in agent_nodes(self.deployment.get("agents", []))
                if isinstance(agent, dict) and agent.get("universal_id")
            }
            if agent_id not in known_agents:
                self.conn.send({
                    "type": "bridge.log.error",
                    "subscription_id": subscription_id,
                    "error": "requested agent is not in this Phoenix deployment session",
                })
                return

            self._bridge_log_tokens[subscription_id] = {
                "subscription_id": subscription_id,
                "agent_id": agent_id,
                "follow": follow,
            }
            packet = Packet()
            packet.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": "hive.log_streamer",
                    "payload": {
                        "target_agent": agent_id,
                        "session_id": self.session_id,
                        "token": subscription_id,
                        "follow": follow,
                        "return_handler": "agent_log_view.update",
                    },
                },
            })
            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=packet,
            )
            self.conn.send({
                "type": "bridge.log.started",
                "session_id": self.session_id,
                "subscription_id": subscription_id,
                "agent_id": agent_id,
                "follow": follow,
            })

        def _bridge_on_log_update(self, payload: dict[str, Any], **_kwargs: Any) -> None:
            content = payload.get("content", {}) if isinstance(payload, dict) else {}
            token = str(content.get("token", "")) if isinstance(content, dict) else ""
            request = self._bridge_log_tokens.get(token)
            if request is None:
                return
            lines = content.get("lines", []) if isinstance(content.get("lines", []), list) else []
            self.conn.send({
                "type": "bridge.log",
                "session_id": self.session_id,
                "subscription_id": token,
                "agent_id": request["agent_id"],
                "follow": request["follow"],
                "lines": lines[:500],
            })
            if not request["follow"]:
                self._bridge_log_tokens.pop(token, None)

        def _bridge_send_agent_tree(self) -> None:
            from phoenix_terminal.bridge.sanitize import public_agent_tree

            rendered = self.tree.get_rendered_tree() if getattr(self, "tree", None) is not None else {}
            self.conn.send({
                "type": "bridge.agent_tree",
                "session_id": self.session_id,
                "agents": public_agent_tree(rendered),
            })

        def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt contract
            try:
                self.bus.off("inbound.verified.agent_log_view.update", self._bridge_on_log_update)
                self._bridge_log_tokens.clear()
            finally:
                super().closeEvent(event)

    session_module.SessionWindow = BridgeSessionWindow
    session_module.run_session(
        session_id,
        SerializedConnection(conn),
        debug_output,
    )
