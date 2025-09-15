import ssl
import socket
import uuid
import http.client
import json
import time
from Crypto.PublicKey import RSA
from matrix_gui.core.utils.spki_utils import verify_spki_pin
from matrix_gui.core.utils.crypto_utils import sign_data
from matrix_gui.modules.net.entity.adapter.agent_cert_wrapper import AgentCertWrapper
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.utils.cert_loader import load_cert_chain_from_memory
from matrix_gui.core.connector_bus import ConnectorBus
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.modules.net.connector.interfaces.connector_base import BaseConnector

class HTTPSConnector(BaseConnector):
    """
    On-demand HTTPS connector.
    Does NOT keep a socket alive.
    Each send builds a TLS tunnel, fires the payload, waits for response,
    and then tears down immediately.
    """

    def __init__(self):
        super().__init__(None, None, None)
        self.host = None
        self.port = None
        self.agent = None
        self.deployment = None
        self.session_id = None
        self._running = {}

    def __call__(self, host, port, agent, deployment, session_id, timeout=10):
        print(f"[HTTPSConnector] Registered for session {session_id}")
        ctx = get_sessions().get(session_id)
        if not ctx:
            print(f"[HTTPSConnector][{agent.get('universal_id')}] ❌ No SessionContext found for {session_id}")
            return

        channel_name = f"{agent['universal_id']}-{session_id[:8]}-{uuid.uuid4().hex[:6]}-https"
        ctx.channels[channel_name] = self
        ctx.status[channel_name] = "ready"

        # Stash connection details so send() knows where to shoot
        self.host = host
        self.port = port
        self.agent = agent
        self.deployment = deployment
        self.session_id = session_id
        return self

    def send(self, packet:Packet, timeout=10):
        if not all([self.host, self.port, self.agent, self.deployment, self.session_id]):
            print("[HTTPSConnector] ❌ Connector not initialized with connection details")
            return

        uid = self.agent.get("universal_id") if self.agent else "unknown"
        print(f"[HTTPSConnector][{uid}] 🎯 Attempting send → {self.host}:{self.port}")
        try:

            self._set_status("connecting")
            inner = packet.get_packet()
            inner["ts"] = int(time.time())

            # Sign with vault private key
            dep = self.deployment or {}
            uid = self.agent.get("universal_id")
            signing = dep.get("certs", {}).get(uid, {}).get("signing", {})
            priv_pem = signing.get("remote_privkey")

            sig_b64 = None
            if priv_pem:

                priv_key = RSA.import_key(priv_pem.encode())
                sig_b64 = sign_data(inner, priv_key)

            outer = {"sig": sig_b64, "content": inner}
            body = json.dumps(outer, separators=(",", ":")).encode()


            # Build SSL context
            cert_adapter = AgentCertWrapper(self.agent, self.deployment)

            cert_pem, key_pem, ca_pem, expected_pin = (
                cert_adapter.cert,
                cert_adapter.key,
                cert_adapter.ca_root_cert,
                cert_adapter.server_spki_pin,
            )
            if not cert_pem or not key_pem:
                print("[HTTPSConnector] ❌ Missing client cert or key for mTLS")
                return None

            ctx_ssl = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            ctx_ssl.check_hostname = False
            ctx_ssl.verify_mode = ssl.CERT_NONE
            load_cert_chain_from_memory(ctx_ssl, cert_pem, key_pem)
            if ca_pem:
                ctx_ssl.load_verify_locations(cadata=ca_pem)

            # Connect
            raw_sock = socket.create_connection((self.host, self.port), timeout=timeout)
            tls_sock = ctx_ssl.wrap_socket(raw_sock, server_hostname=self.host)
            https_conn = http.client.HTTPSConnection(self.host, port=self.port, context=ctx_ssl)
            https_conn.sock = tls_sock

            # Verify SPKI pin
            peer_cert = tls_sock.getpeercert(binary_form=True)
            ok, actual_pin = verify_spki_pin(peer_cert, expected_pin)
            if not ok:
                print(f"[HTTPSConnector][{uid}] ❌ SPKI mismatch. Got: {actual_pin}")
                https_conn.close()
                return None
            print(f"[HTTPSConnector][{uid}] ✅ SPKI verified: {actual_pin}")

            # Fire payload
            https_conn.request("POST", "/matrix", body, headers={"Content-Type": "application/json"})
            resp = https_conn.getresponse()
            data = resp.read().decode(errors="ignore")
            print(f"[HTTPSConnector] 🚀 Sent {packet.get_packet().get('handler', 'none')} → HTTPS {resp.status}")
            if data:
                print(f"[HTTPSConnector] ↩️ Response: {data[:200]}")

            https_conn.close()
            tls_sock.close()
            raw_sock.close()
            self._set_status("connected")

        except Exception as e:

            print(f"[HTTPSConnector][{uid}] ❌ Send error to {self.host}:{self.port} → {e}")

        self._set_status("disconnected")

    def close(self, session_id=None, channel_name=None):
        """
        No persistent socket to close. Just emit status.
        """
        if session_id and channel_name:
            ctx = get_sessions().get(session_id)
            if ctx:
                ctx.channels.pop(channel_name, None)
                ctx.status[channel_name] = "disconnected"
            ConnectorBus.get(session_id).emit(
                "channel.status",
                session_id=session_id,
                channel=channel_name,
                status="disconnected"
            )
