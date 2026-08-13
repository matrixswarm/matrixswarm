import ssl
import socket
import base64
import os

from matrix_gui.core.utils.spki_utils import verify_spki_pin
from matrix_gui.core.utils.cert_loader import load_cert_chain_from_memory
from matrix_gui.modules.net.entity.adapter.agent_cert_wrapper import AgentCertWrapper
def _establish_tls_socket(host, port, agent, deployment, timeout=5):
    cert_adapter = AgentCertWrapper(agent, deployment)
    required_tls = {
        "CA root": cert_adapter.ca_root_cert,
        "client certificate": cert_adapter.cert,
        "client key": cert_adapter.key,
        "server SPKI pin": cert_adapter.server_spki_pin,
    }
    missing_tls = [name for name, value in required_tls.items() if not value]
    if missing_tls:
        raise ValueError(
            "Missing required WSS trust material: " + ", ".join(missing_tls)
        )

    context = ssl.create_default_context(
        ssl.Purpose.SERVER_AUTH,
        cadata=cert_adapter.ca_root_cert,
    )
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    _, cert_path, key_path = load_cert_chain_from_memory(
        context,
        cert_adapter.cert,
        cert_adapter.key,
    )

    raw_sock = tls_sock = None
    try:
        raw_sock = socket.create_connection((host, port), timeout=timeout)
        tls_sock = context.wrap_socket(raw_sock, server_hostname=host)

        peer_cert = tls_sock.getpeercert(binary_form=True)
        ok, actual_pin = verify_spki_pin(
            peer_cert,
            cert_adapter.server_spki_pin,
        )
        if not ok:
            raise ConnectionError(
                "SPKI mismatch: expected "
                f"{cert_adapter.server_spki_pin}, got {actual_pin}"
            )

        # WebSocket upgrade
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
        response = tls_sock.recv(4096)
        if b"101 Switching Protocols" not in response:
            raise ConnectionError("WebSocket upgrade failed")

        return tls_sock
    except Exception:
        if tls_sock:
            tls_sock.close()
        elif raw_sock:
            raw_sock.close()
        raise
    finally:
        for path in (cert_path, key_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass