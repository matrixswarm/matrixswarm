import ssl
import os
import tempfile
import uuid
import hashlib
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from matrix_gui.core.utils.spki_utils import extract_spki_pin_from_der

def load_cert_chain_from_memory(ctx: ssl.SSLContext, cert_pem: str, key_pem: str) -> str:
    """
    Load cert and key from memory into SSLContext securely.
    Returns: pin (SHA256 of SPKI)
    """

    unique_id = uuid.uuid4().hex[:6]
    cert_path = f"{tempfile.gettempdir()}/cert_{unique_id}.pem"
    key_path = f"{tempfile.gettempdir()}/key_{unique_id}.pem"

    try:
        with open(cert_path, 'w') as cert_file:
            cert_file.write(cert_pem)
        with open(key_path, 'w') as key_file:
            key_file.write(key_pem)

        # Load into context
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)

        # === Debug: Print fingerprint
        fingerprint = hashlib.sha256(cert_pem.encode()).hexdigest()[:16]
        print(f"[CERT_LOADER] Loaded cert_fp={fingerprint} → {cert_path}")

        # Extract SPKI pin
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        cert_der = cert.public_bytes(serialization.Encoding.DER)
        pin = extract_spki_pin_from_der(cert_der)

        return pin

    finally:
        # DO NOT delete immediately; let TLS handshake fully complete
        # You may delete these in session cleanup if needed
        print(f"[CERT_LOADER] 🔐 Temp files retained for TLS use: {cert_path}, {key_path}")
        # If you must delete, use: os.remove(cert_path), os.remove(key_path)



def load_ca_into_context(ctx: ssl.SSLContext, ca_pem: str):
    """
    Load CA cert directly from PEM string (in-memory).
    """
    ctx.load_verify_locations(cadata=ca_pem)
