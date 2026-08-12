# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import os, ssl, json, time, socket, tempfile
from websocket import create_connection
from Crypto.PublicKey import RSA

from websocket._exceptions import WebSocketTimeoutException
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.net.entity.adapter.agent_cert_wrapper import AgentCertWrapper
from matrix_gui.core.utils.spki_utils import verify_spki_pin
from matrix_gui.core.utils import crypto_utils
from matrix_gui.core.connector_bus import ConnectorBus
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.modules.net.connector.interfaces.base_connector import BaseConnector

def _write_temp_pem(data: str, suffix=".pem"):
    """
    Write certificate or key data to a secure temporary PEM file.

    Args:
        data (str): PEM-formatted certificate or key.
        suffix (str): File suffix (default ".pem").

    Returns:
        str: Filesystem path to the created temporary PEM file.
    """
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as f:
        f.write(data)
    return path

def _establish_connection(host, port, agent, deployment, session_id, timeout=5):
    """
    Create and authenticate a secure WebSocket connection.

    1. Writes client cert/key to temp PEM files.
    2. Opens WSS socket with disabled hostname/CERT checks.
    3. Verifies server SPKI pin.
    4. Sends a signed 'hello' handshake message.
    5. Cleans up temp PEM files.

    Args:
        host (str): WebSocket server hostname.
        port (int): WebSocket server port.
        agent (dict): Agent metadata including 'universal_id'.
        deployment (dict): Deployment context with certificates.
        session_id (str): Session identifier for this connection.
        timeout (int): TCP connection timeout in seconds.

    Returns:
        websocket.WebSocket | None: Active WebSocket on success, else None.
    """
    cert_adapter = AgentCertWrapper(agent, deployment)
    cert_path = key_path = None
    try:
        cert_path = _write_temp_pem(cert_adapter.cert)
        key_path = _write_temp_pem(cert_adapter.key)
        url = f"wss://{host}:{port}/ws"

        ws = create_connection(
            url,
            timeout=timeout,
            sslopt={
                "certfile": cert_path,
                "keyfile": key_path,
                "cert_reqs": ssl.CERT_NONE,
                "check_hostname": False,
            },
        )

        # SPKI verify
        peer_cert = ws.sock.getpeercert(binary_form=True)
        ok, actual_pin = verify_spki_pin(peer_cert, cert_adapter.server_spki_pin)
        if not ok:
            ws.close()
            raise ConnectionError(f"SPKI mismatch: expected {cert_adapter.server_spki_pin}, got {actual_pin}")

        # signed hello
        hello = {
            "type": "hello",
            "session_id": session_id,
            "agent": agent.get("universal_id"),
            "ts": int(time.time()),
        }
        priv_pem = deployment.get("certs", {}).get(agent.get("universal_id"), {}).get("signing", {}).get("remote_privkey")
        priv_key = RSA.import_key(priv_pem.encode())
        hello["sig"] = crypto_utils.sign_data(hello, priv_key)
        ws.send(json.dumps(hello))
        ws.settimeout(60)
        return ws

    except Exception as e:
        emit_gui_exception_log(f"[wss._establish_connection][{agent.get('universal_id')}] connect error", e)
        return None
    finally:
        for p in (cert_path, key_path):
            if p and os.path.exists(p):
                os.remove(p)
        print(f"[CERT_LOADER][WSS] 🧹 Cleaned up {cert_path}, {key_path}")
# ----------------------------------------------------------------------
class WSSConnector(BaseConnector):
    """
    Persistent WebSocket connector for Matrix packet streams over TLS.

    Implements BaseConnector for a long-lived WSS connection:
      - loop_tick(): one iteration of receiving, heartbeat, and dispatch
      - send(): publish outbound packets on the WebSocket
      - close(): tear down the socket and emit final status

    Attributes:
        _websocket (websocket.WebSocket): Active WebSocket instance or None.
        _last_pong (float): Timestamp of the last successful receive or ping.
    """

    def __init__(self, shared=None):
        """
        Initialize internal state for persistent WebSocket.

        Args:
            shared (dict, optional): Shared context including 'session_id',
                'agent', 'deployment', and initial 'packet' if any.
        """
        super().__init__(shared=shared)
        self._websocket = None
        self._last_pong = 0


    # ----------------------------- main loop ---------------------------
    def loop_tick(self):
        """
        Perform one receive-and-dispatch cycle with heartbeat management.

        - Connect if socket is missing or stale.
        - Receive a message, update pong timestamp, emit inbound event.
        - Handle socket errors, timeouts, and ghost sockets.
        - Sleep briefly to pace the loop.
        """
        continue_loop = False
        try:

            if not self._websocket:
                self._connect_socket()
                print(f"Establishing websocket connection...")
                if self._websocket:
                    continue_loop=True

            else:

                self._emit_status("connected")
                msg = self._websocket.recv()

                # Handle Windows ghost sockets (recv() returns None or empty)
                if not msg:
                    print("[WSSConnector] ⚠️ Empty recv() — treating as dead socket.")
                    raise ConnectionError("socket silent/dead")

                ConnectorBus.get(self.session_id).emit(
                    "inbound.raw",
                    session_id=self.session_id,
                    channel=self.agent.get("universal_id"),
                    source=self.agent.get("universal_id"),
                    payload=json.loads(msg),
                    ts=time.time(),
                )

                self._keep_alive()
                continue_loop=True

        except (socket.timeout, TimeoutError, WebSocketTimeoutException) as e:
            emit_gui_exception_log(f"[WSSConnector] 💀 Socket timeout ({type(e).__name__})", e)
        except (ConnectionResetError, ConnectionAbortedError, ConnectionError, OSError) as e:
            emit_gui_exception_log(f"[WSSConnector] 💀 Socket failure detected ({type(e).__name__})", e)

        return continue_loop

    # ----------------------------- helpers -----------------------------
    def _connect_socket(self):
        """
        Establish or re-establish the WebSocket connection.

        Uses _establish_connection helper; on success, updates status
        and timestamps, else retries after a pause.
        """
        sid = self.session_id
        agent = self.agent
        dep = self.deployment
        conn = agent.get("connection", {})
        host, port = conn.get("host"), conn.get("port")

        if not host or not port:
            print(f"[WSSConnector] Missing host/port for {sid}")
            time.sleep(2)
            return

        ws = _establish_connection(host, port, agent, dep, sid)
        if ws:
            self._websocket = ws
            self._emit_status("connected", host, port)
            print(f"[WSSConnector] Connected to {host}:{port}")
        else:
            self._emit_status("disconnected")
            time.sleep(5)

    def _keep_alive(self):
        try:
            if self._last_pong:
                lp = time.time() -self._last_pong
                print(f"last ping {lp} seconds ago")
            self._last_pong = time.time()

        except Exception as e:
            print(f"[WSSConnector] 💀 keep-alive failed: {e}")
            raise ConnectionError("no pong")

    def _close_socket(self):
        """
        Close the underlying WebSocket and reset the instance reference.
        """
        try:
            if self._websocket:
                self._websocket.close()
        except Exception:
            pass
        self._websocket = None

    # ----------------------------- abstract impls ----------------------
    def send(self, packet: Packet, timeout=10):
        """
        Send a Matrix packet outbound over the WebSocket.

        Args:
            packet (Packet): The packet to serialize and send.
            timeout (int): Unused; for signature consistency with BaseConnector.
        """
        if not self._websocket:
            print(f"[WSSConnector] no socket for {self.session_id}")
            return
        try:
            self._websocket.send(json.dumps(packet.get_packet()))
        except Exception as e:
            print(f"[WSSConnector] send fail: {e}")

    def close(self, session_id=None, channel_name=None):
        """
        Tear down the WebSocket, emit final status, and mark as disconnected.

        Args:
            session_id (str, optional): Session identifier for the event.
            channel_name (str, optional): Channel name (defaults to 'wss').
        """
        self._close_socket()
        self._emit_status("disconnected")
