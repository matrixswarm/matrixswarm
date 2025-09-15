import os
import uuid
import threading
import tempfile
import socket
from matrix_gui.config.boot.globals import get_sessions
import ssl, json, time
from websocket import create_connection
from matrix_gui.modules.net.entity.adapter.agent_cert_wrapper import AgentCertWrapper
from matrix_gui.core.utils.spki_utils import verify_spki_pin
from matrix_gui.core.utils import crypto_utils
from Crypto.PublicKey import RSA
from matrix_gui.core.connector_bus import ConnectorBus
from matrix_gui.modules.net.connector.interfaces.connector_base import BaseConnector
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

def write_temp_pem(data: str, suffix=".pem"):
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(data)
    return path

def establish_ws_connection(host, port, agent, deployment, session_id, timeout=5):
    cert_adapter = AgentCertWrapper(agent, deployment)

    # Write cert + key to temp files (Windows safe)
    cert_path = write_temp_pem(cert_adapter.cert)
    key_path  = write_temp_pem(cert_adapter.key)

    try:
        url = f"wss://{host}:{port}/ws"
        ws = create_connection(
            url,
            timeout=timeout,
            sslopt={
                "certfile": cert_path,
                "keyfile": key_path,
                "cert_reqs": ssl.CERT_NONE,   # critical: disable CA chain checks
                "check_hostname": False,      # skip hostname match
            }
        )

        ws.settimeout(None)  # block forever for reads

        # SPKI pin verification
        peer_cert = ws.sock.getpeercert(binary_form=True)
        ok, actual_pin = verify_spki_pin(peer_cert, cert_adapter.server_spki_pin)
        if not ok:
            ws.close()
            raise ConnectionError(f"SPKI mismatch: expected {cert_adapter.server_spki_pin}, got {actual_pin}")

        ws.settimeout(None)

        # Build hello
        hello = {
            "type": "hello",
            "session_id": session_id,
            "agent": agent.get("universal_id"),
            "ts": int(time.time())
        }

        # Load signing key from deployment if present
        priv_pem = deployment.get("certs", {}).get(agent.get("universal_id"), {}).get("signing", {}).get("remote_privkey")
        if priv_pem:
            priv_key = RSA.import_key(priv_pem.encode())
            hello["sig"] = crypto_utils.sign_data(hello, priv_key)

        ws.send(json.dumps(hello))
        return ws

    except Exception as e:
        print(f"[WSSConnector][{agent.get('universal_id')}] connect error: {e}")

    finally:
        for p in [cert_path, key_path]:
            if p and os.path.exists(p):
                os.remove(p)


class WSSConnector(BaseConnector):
    def __call__(self, host, port, agent, deployment, session_id, timeout=10):

        #print(f"[DEBUG] {agent.get('universal_id')} attaching to session {session_id}")
        try:
            channel_name = f"{agent.get('universal_id')}-{session_id[:8]}-{uuid.uuid4().hex[:6]}-wss"
            self._running[session_id] = True
            thread = threading.Thread(
                target=self._run_connector_loop,
                args=(host, port, agent, deployment, session_id, channel_name),
                daemon=True,
                name=f"{agent.get('universal_id')}-wss"
            )
            thread.start()
        except Exception as e:
            emit_gui_exception_log("wss.__call__", e)


    def __init__(self, running=True):

        try:
            self._running = {}
            ConnectorBus.get("global").on("session.closed", self._on_session_closed)
        except Exception as e:
            emit_gui_exception_log("wss.__init__", e)

    def send(self, packet: Packet, timeout=10):
        print('send is not  implemented')
        pass

    def _run_connector_loop(self, host, port, agent, deployment, session_id, channel_name):
        try:
            ctx = get_sessions().get(session_id)
            self._set_channel_name(channel_name)
            self._set_status("connecting")
            if not ctx:
                return

        except Exception as e:
            emit_gui_exception_log("wss._run_connector_loop", e)

        while self._running.get(session_id, False):  # high-level reconnect loop
            ws = None
            try:

                ws = establish_ws_connection(host, port, agent, deployment, session_id, timeout=10)

                # Register channel
                ctx.channels[channel_name] = ws
                ctx.status[channel_name] = "connected"
                self._set_status("connected")
                ConnectorBus.get(session_id).emit(
                    "channel.status",
                    session_id=session_id,
                    channel=channel_name,
                    status="connected",
                    info={"host": host, "port": port}
                )

                # recv loop
                while self._running.get(session_id, False):
                    try:
                        message = ws.recv()

                        if not message:
                            raise ConnectionError("empty recv → disconnect")
                        ConnectorBus.get(session_id).emit(
                            "inbound.raw",
                            session_id=session_id,
                            channel=channel_name,
                            source=agent.get("universal_id"),
                            payload=json.loads(message),
                            ts=time.time()
                        )

                        print(f"[DEBUG][WSS] emitted inbound.raw for {session_id}")

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

                ConnectorBus.get(session_id).emit(
                    "channel.status",
                    session_id=session_id,
                    channel=channel_name,
                    status="disconnected"
                )
                ctx.status[channel_name] = "disconnected"
                self._set_status("disconnected")

                if not self._running.get(session_id, False) or not get_sessions().get(session_id):
                    break  # don’t sleep/reconnect if closed

                time.sleep(5)

        self._running.pop(session_id, None)

    def close(self, session_id=None, channel_name=None):
        """
        Stop the WSS loop, close sockets, and clean up channel(s).
        """
        try:
            if not session_id:
                return

            print(f"[WSSConnector] 🔴 Closing session {session_id}")
            self._running[session_id] = False

            ctx = get_sessions().get(session_id)
            if not ctx:
                return

            # If a specific channel is given
            if channel_name and channel_name in ctx.channels:
                ws = ctx.channels.pop(channel_name, None)
                ctx.status[channel_name] = "disconnected"
                try:
                    if ws:
                        ws.close(status=1000, reason="manual close")
                except Exception as e:
                    print(f"[WSSConnector] ⚠ error closing {channel_name}: {e}")
                ConnectorBus.get(session_id).emit(
                    "channel.status",
                    session_id=session_id,
                    channel=channel_name,
                    status="disconnected"
                )
                ctx.status[channel_name] = "disconnected"
                self._set_status("disconnected")

            # Otherwise nuke all WSS channels for this session
            else:
                for ch, ws in list(ctx.channels.items()):
                    if ch.endswith("-wss"):
                        try:
                            if ws:
                                ws.close(status=1000, reason="session close")
                        except Exception:
                            pass
                        ctx.status[ch] = "disconnected"
                        ConnectorBus.get(session_id).emit(
                            "channel.status",
                            session_id=session_id,
                            channel=ch,
                            status="disconnected"
                        )
                        ctx.channels.pop(ch, None)

        except Exception as e:
            emit_gui_exception_log("wss.close", e)


    def _on_session_closed(self, session_id, **_):
        # Delegate to close() so cleanup is unified
        print(f"[WSSConnector] 🔴 session.closed received for {session_id}")
        self.close(session_id=session_id)