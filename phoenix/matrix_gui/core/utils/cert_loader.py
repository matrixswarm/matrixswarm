import os
import ssl
import tempfile
import uuid
import hashlib
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from matrix_gui.core.utils.spki_utils import extract_spki_pin_from_der

def load_cert_chain_from_memory(ctx: ssl.SSLContext, cert_pem: str, key_pem: str):
    """
    Load cert and key from memory into SSLContext securely.
    Returns: pin (SHA256 of SPKI)
    """
    unique_id = uuid.uuid4().hex[:6]

    temp_dir = tempfile.gettempdir()
    cert_path = os.path.join(temp_dir, f"cert_{unique_id}.pem")
    key_path  = os.path.join(temp_dir, f"key_{unique_id}.pem")

    try:
        with open(cert_path, "w") as cert_file:
            cert_file.write(cert_pem)
        with open(key_path, "w") as key_file:
            key_file.write(key_pem)

        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)

        fingerprint = hashlib.sha256(cert_pem.encode()).hexdigest()[:16]
        print(f"[CERT_LOADER] Loaded cert_fp={fingerprint} → {os.path.normpath(cert_path)}")

        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        cert_der = cert.public_bytes(serialization.Encoding.DER)
        pin = extract_spki_pin_from_der(cert_der)

        return pin, cert_path, key_path

    finally:
        # DO NOT delete immediately; let TLS handshake fully complete
        print(f"[CERT_LOADER] 🔐 Temp files retained for TLS use: "
              f"{os.path.normpath(cert_path)}, {os.path.normpath(key_path)}")



def load_ca_into_context(ctx: ssl.SSLContext, ca_pem: str):
    """
    Load CA cert directly from PEM string (in-memory).
    """
    ctx.load_verify_locations(cadata=ca_pem)
