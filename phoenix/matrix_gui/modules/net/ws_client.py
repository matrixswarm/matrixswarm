
import json
import io
import os
import traceback
from ssl import SSLContext, PROTOCOL_TLS_CLIENT, CERT_REQUIRED
import socket
import ssl
import base64
from websocket import WebSocket


from matrix_gui.core.event_bus import EventBus
from matrix_gui.core.utils.spki_utils import verify_spki_pin
from matrix_gui.core.utils.cert_loader import load_cert_chain_from_memory, load_ca_into_context

class WebSocketClient:
    def __init__(self, session_id, channel, tls_cert=None, tls_key=None, expected_pin=None, ca_cert=None):

        self.session_id = session_id
        self.channel = channel
        self.tls_cert = tls_cert
        self.tls_key = tls_key
        self.expected_pin = expected_pin
        self.ws = None
        self._cert_path = None
        self._key_path = None
        self.ca_cert = ca_cert

    def connect_for_session(self, host, port):
        print(f"[DEBUG] Connecting to wss://{host}:{port}/ws")
        try:

            raw_sock = socket.create_connection((host, port))
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            # Load client identity
            load_cert_chain_from_memory(ctx, self.tls_cert, self.tls_key)

            tls_sock = ctx.wrap_socket(raw_sock, server_hostname=host)

            # === SPKI pin verification
            peer_cert = tls_sock.getpeercert(binary_form=True)
            ok, actual_pin = verify_spki_pin(peer_cert, self.expected_pin)
            if not ok:
                tls_sock.close()
                raise ssl.SSLError(f"[SPKI] Mismatch! Expected {self.expected_pin}, got {actual_pin}")
            print(f"[SPKI] ✅ Verified pin: {actual_pin}")

            ws = WebSocket()
            ws.settimeout(10)

            # Manually send the WebSocket upgrade headers
            key = base64.b64encode(os.urandom(16)).decode()
            headers = (
                f"GET /ws HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()

            tls_sock.sendall(headers)

            # Receive server handshake
            response = tls_sock.recv(4096)
            if b"101 Switching Protocols" not in response:
                raise RuntimeError("WebSocket upgrade failed")

            # Attach the open socket to WebSocket object
            ws.sock = tls_sock
            ws.connected = True
            self.ws = ws


        except Exception as e:
            print("❌ [SSL DEBUG] Connection failed:", e)
            print(traceback.format_exc())
            raise


    def send(self, message):
        if not self.ws:
            raise RuntimeError("WebSocket not connected")
        payload = json.dumps(
            {"session": self.session_id, "channel": self.channel, "data": message}
        )
        self.ws.send(payload)

    def recv(self):
        if not self.ws:
            raise RuntimeError("WebSocket not connected")
        return self.ws.recv()

    def close(self):
        if self.ws:
            self.ws.close()
            self.ws = None
        # Cleanup tempfiles
        for path in (self._cert_path, self._key_path):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception:
                    pass




def initialize():
    EventBus.on("ws.connect.for_session", WebSocketClient.connect_for_session)
    print("[WebSocketClient] Listener online (initialized).")
