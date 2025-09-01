import ssl
import socket
import http.client
from matrix_gui.core.utils.spki_utils import verify_spki_pin
from matrix_gui.modules.net.entity.adapter.agent_cert_wrapper import AgentCertWrapper
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.utils.cert_loader import load_cert_chain_from_memory
from matrix_gui.core.event_bus import EventBus

class HTTPSConnector:
    def __call__(self, host, port, agent, deployment, session_id):

        print(f"[DEBUG] {agent.get('universal_id')} attaching to session {session_id}")

        ctx = get_sessions().get(session_id)
        if not ctx:
            print(f"[HTTPSConnector][{agent.get('universal_id')}] ❌ No SessionContext found for {session_id}")
            return

        uid=""
        try:
            cert_adapter = AgentCertWrapper(agent, deployment)
            cert_pem = cert_adapter.cert
            key_pem = cert_adapter.key
            ca_pem = cert_adapter.ca_root_cert
            expected_pin = cert_adapter.spki_pin
            uid = cert_adapter.uid

            if not cert_pem or not key_pem:
                print("[HTTPSConnector] Missing client cert or key for mTLS")
                return None

            # 1. Build SSL context
            ctx_ssl = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
            ctx_ssl.check_hostname = False
            ctx_ssl.verify_mode = ssl.CERT_NONE  # SPKI replaces CA enforcement
            load_cert_chain_from_memory(ctx_ssl, cert_pem, key_pem)
            if ca_pem:
                ctx_ssl.load_verify_locations(cadata=ca_pem)

            # 2. Connect raw socket + wrap in TLS
            raw_sock = socket.create_connection((host, port))
            tls_sock = ctx_ssl.wrap_socket(raw_sock, server_hostname=host)

            # 3. SPKI pin verification
            peer_cert = tls_sock.getpeercert(binary_form=True)
            ok, actual_pin = verify_spki_pin(peer_cert, expected_pin)
            if not ok:
                print(f"[HTTPSConnector][{uid}] ❌ SPKI mismatch. Got: {actual_pin}")
                tls_sock.close()
                return None

            print(f"[HTTPSConnector][{uid}] ✅ SPKI verified: {actual_pin}")

            # 4. Bind verified TLS socket to HTTPSConnection
            https_conn = http.client.HTTPSConnection(host=host, port=port)
            https_conn.sock = tls_sock

            uid = agent.get("universal_id")
            channel_name = f"{uid}-https"
            ctx.channels[channel_name] = https_conn
            ctx.status[channel_name] = "connected"
            EventBus.emit("channel.status",
                          session_id=session_id,
                          channel=channel_name,
                          status="connected",
                          info={"host": host, "port": port})
            return https_conn


        except Exception as e:
            print(f"[HTTPSConnector][{uid}] Connection error:", e)
            for key in list(ctx.channels.keys()):
                if key.endswith("-https"):
                    del ctx.channels[key]
            if not ctx.channels:
                get_sessions().destroy(session_id)
                print(f"[HTTPSConnector][{uid}] Session {session_id} closed")

    def close(self, conn, session_id=None, channel_name=None):
        try:
            conn.close()
        except Exception:
            pass
        if session_id and channel_name:
            ctx = get_sessions().get(session_id)
            if ctx:
                ctx.channels.pop(channel_name, None)
                ctx.status[channel_name] = "disconnected"
                EventBus.emit("channel.status",
                              session_id=session_id,
                              channel=channel_name,
                              status="disconnected")