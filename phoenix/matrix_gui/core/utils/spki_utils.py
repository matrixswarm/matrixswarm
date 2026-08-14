import base64
import hashlib
import hmac

from cryptography import x509
from cryptography.hazmat.primitives import serialization


def extract_spki_pin_from_der(cert_der: bytes) -> str:
    if not isinstance(cert_der, bytes) or not cert_der:
        raise ValueError("A non-empty DER certificate is required for SPKI pinning")

    cert = x509.load_der_x509_certificate(cert_der)
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(hashlib.sha256(spki).digest()).decode()


def verify_spki_pin(cert_der: bytes, expected_pin: str) -> tuple[bool, str]:
    if not isinstance(expected_pin, str) or not expected_pin.strip():
        raise ValueError("A non-empty expected SPKI pin is required")

    expected = expected_pin.strip()
    if expected.startswith("sha256/"):
        expected = expected.removeprefix("sha256/")

    actual_pin = extract_spki_pin_from_der(cert_der)
    return hmac.compare_digest(actual_pin, expected), actual_pin
