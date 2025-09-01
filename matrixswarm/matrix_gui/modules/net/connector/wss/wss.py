import threading
import time
import json
import socket
from websocket import WebSocket
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.event_bus import EventBus
from .establish_tls_socket import _establish_tls_socket

class WSSConnector:
    def __init__(self, running=True):
        self._running = {}
        EventBus.on("session.closed", self._on_session_closed)

    def __call__(self, host, port, agent, deployment, session_id):
        channel_name = f"{agent.get('universal_id')}-wss"
        self._running[session_id] = True
        thread = threading.Thread(
            target=self._run_connector_loop,
            args=(host, port, agent, deployment, session_id, channel_name),
            daemon=True,
            name=f"{agent.get('universal_id')}-wss"
        )
        thread.start()

    def _run_connector_loop(self, host, port, agent, deployment, session_id, channel_name):
        ctx = get_sessions().get(session_id)
        if not ctx:
            return

        while self._running.get(session_id, False):  # high-level reconnect loop
            ws = None
            try:
                tls_sock = _establish_tls_socket(host, port, agent, deployment, session_id)
                ws = WebSocket()
                ws.settimeout(None)
                ws.sock = tls_sock

                hello = {
                    "type": "hello",
                    "session_id": session_id,
                    "agent": agent.get("universal_id"),
                    "ts": int(time.time())
                }
                ws.send(json.dumps(hello))

                # register channel
                ctx.channels[channel_name] = ws
                ctx.status[channel_name] = "connected"
                EventBus.emit("channel.status", session_id=session_id,
                              channel=channel_name, status="connected",
                              info={"host": host, "port": port})

                # recv loop
                while self._running.get(session_id, False):
                    try:
                        message = ws.recv()
                        if not message:
                            raise ConnectionError("empty recv → disconnect")
                        EventBus.emit("inbound.message",
                                      session_id=session_id,
                                      channel=channel_name,
                                      source=agent.get("universal_id"),
                                      payload=json.loads(message),
                                      ts=time.time())
                    except Exception as e:
                        print(f"[WSSConnector][{agent['universal_id']}] recv error: {e}")
                        break

            except Exception as e:
                print(f"[WSSConnector][{agent['universal_id']}] connect error: {e}")


            finally:

                # cleanup
                ctx.status[channel_name] = "disconnected"
                ctx.channels.pop(channel_name, None)
                try:
                    if ws:
                        ws.close()
                except Exception:
                    pass

                try:
                    if ws and ws.sock:
                        ws.sock.shutdown(socket.SHUT_RDWR)
                        ws.close(status=1000, reason="client shutdown")
                except Exception as e:
                    print(f"[WSSConnector] ⚠️ error hard-closing socket: {e}")

                EventBus.emit("channel.status", session_id=session_id, channel=channel_name, status="disconnected")

                if not self._running.get(session_id, False) or not get_sessions().get(session_id):
                    break  # don’t sleep/reconnect if closed

                time.sleep(5)

        self._running.pop(session_id, None)

    def _on_session_closed(self, session_id, **_):
        print(f"[WSSConnector] 🔴 session.closed received for {session_id}")
        self._running[session_id] = False
        ctx = get_sessions().get(session_id)
        if ctx:
            for channel_name, ws in list(ctx.channels.items()):
                if channel_name.endswith("-wss"):
                    try:

                        print(f"[WSSConnector] 🔌 closing {channel_name}")
                        if self._running.get(session_id, False):
                            try:
                                if ws:
                                    ws.close(status=1000, reason="loop cleanup")
                            except Exception:
                                pass

                    except Exception as e:
                        print(f"[WSSConnector] ⚠️ error closing {channel_name}: {e}")
                    EventBus.emit("channel.status",
                                  session_id=session_id,
                                  channel=channel_name,
                                  status="disconnected")
            ctx.channels.clear()