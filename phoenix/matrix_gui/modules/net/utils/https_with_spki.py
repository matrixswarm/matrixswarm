import ssl, socket
import logging
from .swarm_trustkit import extract_spki_pin_from_cert

log = logging.getLogger("https_with_spki")

def https_with_spki(host, port, expected_pin, cert_file=None, key_file=None, ca_cert=None):
    if not expected_pin:
        raise ValueError("SPKI pin required")

    if not cert_file or not key_file:
        log.warning(f"[HTTPS] Missing client cert or key for mTLS to {host}:{port}")

    # Create context
    if ca_cert:
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.load_verify_locations(ca_cert)
        log.info(f"[HTTPS] Using CA verification with {ca_cert}")
    else:
        context = ssl._create_unverified_context()  # disables CA/hostname check
        log.warning("[HTTPS] No CA cert provided. Hostname and CA checks are disabled.")

    if cert_file and key_file:
        context.load_cert_chain(certfile=cert_file, keyfile=key_file)

    # Create and wrap socket
    conn = socket.create_connection((host, port))
    sock = context.wrap_socket(conn, server_hostname=host)

    # Extract server cert and SPKI pin
    server_cert_der = sock.getpeercert(binary_form=True)
    pin = extract_spki_pin_from_cert(server_cert_der)

    if pin != expected_pin:
        sock.close()
        raise Exception(f"[HTTPS] SPKI pin mismatch! Expected {expected_pin}, got {pin}")

    log.info(f"[HTTPS][PIN-OK] SPKI {pin} matched for {host}")
    return sock
