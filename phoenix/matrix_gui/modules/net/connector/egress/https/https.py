# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import os, ssl, socket, http.client, json, time, uuid
from Crypto.PublicKey import RSA
from matrix_gui.core.utils.spki_utils import verify_spki_pin
from matrix_gui.core.utils.crypto_utils import sign_data
from matrix_gui.modules.net.entity.adapter.agent_cert_wrapper import AgentCertWrapper
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.utils.cert_loader import load_cert_chain_from_memory
from matrix_gui.core.connector_bus import ConnectorBus
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.modules.net.connector.interfaces.base_connector import BaseConnector


class HTTPSConnector(BaseConnector):
    """
    Single-use HTTPS connector for sending Matrix packets over TLS.

    Implements the BaseConnector interface for a one-shot HTTPS “catapult”:
      - run_once(): performs a single transmission and exits
      - send(): encapsulates, signs, secures, and dispatches the packet
      - close(): emits a final disconnection event

    Attributes:
        proto (str): Protocol name (“https”).
        host (str): Remote hostname for the HTTPS endpoint.
        port (int): Remote port number for the HTTPS endpoint.
    """

    def __init__(self, shared=None):
        """
        Initialize the HTTPSConnector, validate context, and set defaults.

        Args:
            shared (dict, optional): Shared context including 'session_id',
                'agent', 'deployment', and 'packet'.
        """
        super().__init__(shared=shared)
        self.proto = "https"
        self._status = "initialized"

        # Quick sanity
        if not self.agent or not self.deployment:
            print("[HTTPSConnector] Missing agent or deployment context.")
            return

        conn = self.agent.get("connection", {}) or {}
        self.host = conn.get("host")
        self.port = conn.get("port")

        if not self.host or not self.port:
            print("[HTTPSConnector] ❌ Missing host or port — abort launch.")

    # ------------------------------------------------------------------
    # CORE SINGLE-MISSION EXECUTION
    # ------------------------------------------------------------------
    def run_once(self):
        """
        Execute one HTTPS send mission then exit.

        Retrieves the packet from shared context, calls send(),
        and signals completion or error before closing.
        """
        try:
            print(f"[HTTPSConnector] Launching HTTPS send for {self.agent.get('universal_id')}")
            self._set_status("connecting")

            packet = self._shared.get("packet")

            if not packet:
                print("[HTTPSConnector] ❌ No packet provided in shared context.")
                return

            self.send(packet)
            print("[HTTPSConnector] Mission complete.")

        except Exception as e:
            print(f"[HTTPSConnector][ERROR] {e}")

        finally:
            # Graceful emit for telemetry / cleanup
            self.close(self.session_id, self.agent.get("universal_id"))

    # ------------------------------------------------------------------
    # TRANSMISSION ROUTINE
    # ------------------------------------------------------------------
    def send(self, packet: Packet, timeout=10):
        """
        Sign, secure, and POST a Matrix packet over HTTPS.

        Args:
            packet (Packet): The Matrix packet to send.
            timeout (int): Seconds to wait for network operations.

        Behavior:
          1. Emit start event on ConnectorBus.
          2. Wrap the packet with timestamp and session metadata.
          3. Sign payload with RSA private key from deployment certs.
          4. Establish a TLS socket with custom CA and client cert.
          5. Verify server SPKI pin.
          6. POST JSON payload to '/matrix' endpoint.
          7. Clean up sockets and temporary cert files.
          8. Emit end event on ConnectorBus.
        """
        ctx = get_sessions().get(self.session_id)
        if not ctx:
            print(f"[HTTPSConnector] ❌ No session context for {self.session_id}")
            return

        # Emit start of transmission
        if hasattr(ctx, "bus"):
            ctx.bus.emit("channel.packet.sent", start_end=1)

        uid = self.agent.get("universal_id")
        https_conn = tls_sock = raw_sock = None
        cert_path = key_path = None
        try:
            inner = {
                "matrix_packet": packet.get_packet(),
                "ts": int(time.time()),
                "session_id": self.session_id,
            }

            #flash connecting on session_window footer
            self._emit_status("connected")

            signing = self.deployment["certs"][uid]["signing"]
            priv_key = RSA.import_key(signing["remote_privkey"].encode())
            sig_b64 = sign_data(inner, priv_key)
            outer = {"sig": sig_b64, "content": inner}
            body = json.dumps(outer).encode()

            # ---- Setup TLS context ----
            cert_adapter = AgentCertWrapper(self.agent, self.deployment)
            required_tls = {
                "CA root": cert_adapter.ca_root_cert,
                "client certificate": cert_adapter.cert,
                "client key": cert_adapter.key,
                "server SPKI pin": cert_adapter.server_spki_pin,
            }
            missing_tls = [name for name, value in required_tls.items() if not value]
            if missing_tls:
                raise ValueError(
                    "Missing required HTTPS trust material: "
                    + ", ".join(missing_tls)
                )

            ctx_ssl = ssl.create_default_context(
                ssl.Purpose.SERVER_AUTH,
                cadata=cert_adapter.ca_root_cert,
            )
            ctx_ssl.check_hostname = True
            ctx_ssl.verify_mode = ssl.CERT_REQUIRED
            _, cert_path, key_path = load_cert_chain_from_memory(
                ctx_ssl, cert_adapter.cert, cert_adapter.key
            )

            # ---- Build secure connection ----
            raw_sock = socket.create_connection((self.host, self.port), timeout=timeout)
            tls_sock = ctx_ssl.wrap_socket(raw_sock, server_hostname=self.host)

            # Verify SPKI
            peer_cert = tls_sock.getpeercert(binary_form=True)
            ok, actual_pin = verify_spki_pin(peer_cert, cert_adapter.server_spki_pin)
            if not ok:
                raise ConnectionError(f"SPKI mismatch: {actual_pin}")

            https_conn = http.client.HTTPSConnection(self.host, self.port, context=ctx_ssl)
            https_conn.sock = tls_sock
            https_conn.request(
                "POST", "/matrix", body, headers={"Content-Type": "application/json"}
            )
            resp = https_conn.getresponse()
            print(f"[HTTPSConnector] 🌐 Sent → HTTPS {resp.status}")

        except Exception as e:
            print(f"[HTTPSConnector] ❌ Send error: {e}")

        finally:
            for resource in (https_conn, tls_sock, raw_sock):
                if resource:
                    try:
                        resource.close()
                    except Exception:
                        pass
            for path in (cert_path, key_path):
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            if hasattr(ctx, "bus"):
                ctx.bus.emit("channel.packet.sent", start_end=0)

    # ------------------------------------------------------------------
    # CLOSE / TELEMETRY
    # ------------------------------------------------------------------
    def close(self, session_id=None, channel_name=None):
        """
        Emit a disconnection event and update status to 'disconnected'.

        Args:
            session_id (str, optional): Session to target for the status event.
            channel_name (str, optional): Channel name, defaults to 'https'.
        """

        self._emit_status("idle")

        #check if we already closed in the base_connector
        if getattr(self, "_closed", False):
            #print(f"[DEBUG][{self.__class__.__name__}] duplicate close() suppressed")
            return
        self._closed = True


