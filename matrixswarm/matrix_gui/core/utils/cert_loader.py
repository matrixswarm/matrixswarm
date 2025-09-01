import ssl
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from matrix_gui.core.utils.spki_utils import extract_spki_pin_from_der
import tempfile
import os


def load_cert_chain_from_memory(ctx: ssl.SSLContext, cert_pem: str, key_pem: str) -> str:
    """
    Load cert and key from memory into SSLContext securely.
    Returns: pin (SHA256 of SPKI)
    """
    # Create temporary files for the cert and key.
    # Python's SSLContext.load_cert_chain requires file paths.
    try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".pem") as cert_file:
            cert_file.write(cert_pem)
            cert_path = cert_file.name

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".pem") as key_file:
            key_file.write(key_pem)
            key_path = key_file.name

        # Now load the certificate chain from the temporary files.
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)

        # Extract the SPKI pin from the certificate.
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        cert_der = cert.public_bytes(serialization.Encoding.DER)
        pin = extract_spki_pin_from_der(cert_der)

        # Return the pin for later use (e.g., SPKI pinning).
        return pin
    finally:
        # Clean up temporary files.
        if 'cert_path' in locals() and os.path.exists(cert_path):
            os.remove(cert_path)
        if 'key_path' in locals() and os.path.exists(key_path):
            os.remove(key_path)


def load_ca_into_context(ctx: ssl.SSLContext, ca_pem: str):
    """
    Load CA cert directly from PEM string (in-memory).
    """
    ctx.load_verify_locations(cadata=ca_pem)
