import os, ssl, json, time
import threading
import tempfile
import socket
from matrix_gui.config.boot.globals import get_sessions

import asyncio
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
    cert_path = key_path = None
    try:
        cert_path = write_temp_pem(cert_adapter.cert)
        key_path = write_temp_pem(cert_adapter.key)
    except Exception as e:
        print(f"[WSSConnector] ❌ Failed to write temp PEMs: {e}")
        return None

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

        # SPKI pin verification
        peer_cert = ws.sock.getpeercert(binary_form=True)
        ok, actual_pin = verify_spki_pin(peer_cert, cert_adapter.server_spki_pin)

        if not ok:
            ws.close()
            raise ConnectionError(f"SPKI mismatch: expected {cert_adapter.server_spki_pin}, got {actual_pin}")

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
        ws.settimeout(None)
        return ws

    except Exception as e:
        print(f"[WSSConnector][{agent.get('universal_id')}] connect error: {e}")


    finally:
        for p in [cert_path, key_path]:
            if p and os.path.exists(p):
                os.remove(p)
        print(f"[CERT_LOADER][WSS] 🧹 Cleaned up {cert_path}, {key_path}")

class WSSConnector(BaseConnector):
    def __init__(self, running=True):
        self._running = {}
        self._socket_map = {}  # sid → ws
        ConnectorBus.get("global").on("session.closed", self._on_session_closed)

    def __call__(self, host, port, agent, deployment, session_id, timeout=10):
        name = f"{agent.get('universal_id')}-wss"
        if self._running.get(session_id):
            print(f"[WSSConnector] session {session_id} already running")
            return
        self._running[session_id] = True
        t = threading.Thread(
            target=self._connector_loop,
            args=(host, port, agent, deployment, session_id, name),
            daemon=True,
            name=name,
        )
        t.start()

    def _connector_loop(self, host, port, agent, deployment, sid, ch_name):
        ctx = get_sessions().get(sid)
        if not ctx:
            return

        backoff = 2
        last_state = None

        while self._running.get(sid, False):
            try:
                ws = establish_ws_connection(host, port, agent, deployment, sid, timeout=5)
                if not ws:
                    raise ConnectionError("connect failed")

                self._socket_map[sid] = ws
                if last_state != "connected":
                    self._emit_status(sid, ch_name, "connected", host, port)
                    last_state = "connected"
                backoff = 2  # reset backoff

                while self._running.get(sid, False):
                    try:
                        msg = ws.recv()
                        if not msg:
                            raise ConnectionError("peer closed")
                        ConnectorBus.get(sid).emit(
                            "inbound.raw",
                            session_id=sid,
                            channel=ch_name,
                            source=agent.get("universal_id"),
                            payload=json.loads(msg),
                            ts=time.time(),
                        )
                    except socket.timeout:
                        # nothing to read — stay connected quietly
                        continue
                    except TimeoutError:
                        continue
                    except (OSError, ConnectionError):
                        break
                    except Exception as e:
                        # log once every few minutes, not per tick
                        print(f"[WSSConnector][{agent['universal_id']}] recv error: {type(e).__name__}")
                        time.sleep(1)
                        break

            except Exception as e:
                if last_state != "disconnected":
                    self._emit_status(sid, ch_name, "disconnected")
                    last_state = "disconnected"
                print(f"[WSSConnector][{agent.get('universal_id')}] {e}")

            # graceful socket cleanup
            try:
                ws.close()
            except Exception:
                pass

            if not self._running.get(sid, False):
                break

            # stay quiet during downtime
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)

        self._socket_map.pop(sid, None)
        self._emit_status(sid, ch_name, "closed")
        print(f"[WSSConnector] loop exit for {sid}")

    # ---------------------

    def _emit_status(self, sid, ch, status, host=None, port=None):
        ConnectorBus.get(sid).emit(
            "channel.status",
            session_id=sid,
            channel=ch,
            status=status,
            info={"host": host, "port": port} if host else {},
        )
        self._set_status(status)

    def send(self, packet: Packet, sid=None):
        ws = self._socket_map.get(sid)
        if not ws:
            print(f"[WSSConnector] no socket for {sid}")
            return
        try:
            ws.send(json.dumps(packet.get_packet()))
        except Exception as e:
            print(f"[WSSConnector] send fail: {e}")

    def close(self, session_id=None, channel_name=None):
        self._running[session_id] = False
        ws = self._socket_map.pop(session_id, None)
        try:
            if ws:
                ws.close()
        except Exception:
            pass
        self._emit_status(session_id, channel_name or "wss", "closed")

    def _on_session_closed(self, session_id, **_):
        self.close(session_id=session_id)
