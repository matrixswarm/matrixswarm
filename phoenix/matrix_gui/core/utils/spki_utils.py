import base64, hashlib
from cryptography import x509
from cryptography.hazmat.primitives import serialization, hashes

def extract_spki_pin_from_der(cert_der: bytes) -> str:
    cert = x509.load_der_x509_certificate(cert_der)
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(hashlib.sha256(spki).digest()).decode()

def verify_spki_pin(cert_der: bytes, expected_pin: str) -> (bool, str):
    actual_pin = extract_spki_pin_from_der(cert_der)
    return actual_pin == expected_pin, actual_pin
