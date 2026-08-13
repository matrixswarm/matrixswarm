import os
import ssl
import tempfile
import hashlib
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from matrix_gui.core.utils.spki_utils import extract_spki_pin_from_der

def load_cert_chain_from_memory(ctx: ssl.SSLContext, cert_pem: str, key_pem: str):
    """
    Load cert and key from memory into SSLContext securely.
    Returns: pin (SHA256 of SPKI)
    """
    cert_path = None
    key_path = None

    try:
        with tempfile.NamedTemporaryFile(
                mode="w",
                delete=False,
                suffix=".pem",
                encoding="utf-8",
        ) as cert_file:
            cert_path = cert_file.name
            cert_file.write(cert_pem)

        with tempfile.NamedTemporaryFile(
                mode="w",
                delete=False,
                suffix=".pem",
                encoding="utf-8",
        ) as key_file:
            key_path = key_file.name
            key_file.write(key_pem)

        os.chmod(cert_path, 0o600)
        os.chmod(key_path, 0o600)
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)

        fingerprint = hashlib.sha256(cert_pem.encode()).hexdigest()[:16]
        print(f"[CERT_LOADER] Loaded cert_fp={fingerprint} → {os.path.normpath(cert_path)}")

        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        cert_der = cert.public_bytes(serialization.Encoding.DER)
        pin = extract_spki_pin_from_der(cert_der)

        return pin, cert_path, key_path

    finally:
        cleanup_error = None
        for path in (cert_path, key_path):
            if not path:
                continue
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                cleanup_error = cleanup_error or exc

        if cleanup_error is not None:
            raise RuntimeError(
                "Failed to remove temporary TLS credential material"
            ) from cleanup_error



def load_ca_into_context(ctx: ssl.SSLContext, ca_pem: str):
    """
    Load CA cert directly from PEM string (in-memory).
    """
    ctx.load_verify_locations(cadata=ca_pem)
