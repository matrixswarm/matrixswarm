from __future__ import annotations
import time, itertools
from typing import Iterable, Dict, Tuple
from cryptography.hazmat.primitives.asymmetric import rsa
from matrix_gui.modules.vault.crypto.cert_factory import manufacture_cert_set_for_tags
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

def _now_iso(): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def _fp_sha256_hex(pem: str) -> str:
    try: return x509.load_pem_x509_certificate(pem.encode()).fingerprint(hashes.SHA256()).hex()
    except Exception: return ""

def _spki_b64(pem: str) -> str:
    try:
        pub = x509.load_pem_x509_certificate(pem.encode()).public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        import base64, hashlib
        return base64.b64encode(hashlib.sha256(pub).digest()).decode()
    except Exception: return ""

def _covers(desired_ips, desired_dns, have_ips, have_dns) -> bool:
    # All desired names must be covered by the existing SANs (order-insensitive)
    return set(desired_ips).issubset(set(have_ips)) and set(desired_dns).issubset(set(have_dns))

def _gen_rsa_keypair_pem(bits=2048):
    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem

def mint_security_tag(tag: str, agent_id: str, conn_data: dict) -> dict:
    from matrix_gui.modules.vault.crypto.cert_factory import manufacture_cert_set_for_tags
    import uuid

    sans = [conn_data.get("host", "0.0.0.0")]
    cert_profile, serial = manufacture_cert_set_for_tags(
        {tag},
        sans_map={tag: sans}
    )

    fields = cert_profile.get(tag, {}) or {}
    cert_pem = fields.get("cert") or fields.get("https_client_cert") or ""
    key_pem = fields.get("key")  or fields.get("https_client_key")  or ""
    ca_pem  = fields.get("ca")   or fields.get("https_ca")          or ""

    spki_pin = fields.get("spki_pin") or _spki_b64(cert_pem)

    cert = {
        "cert": cert_pem,
        "key": key_pem,
        "ca": ca_pem,
        "remote_pubkey": fields.get("remote_pubkey", ""),
        "cn": f"{tag}-{agent_id}-serial_{(fields.get('serial') or serial or '')}".strip("-_"),
        "sans": {
            "ip": [conn_data.get("host", "0.0.0.0")]
        },
        "fingerprint_sha256": _fp_sha256_hex(cert_pem),
        "spki_pin": spki_pin,
        "created_at": _now_iso()
    }

    return {
        "security-tag": {
            "tag": tag,
            "certs": {
                "signing": cert,
                "connection": cert
            }
        }
    }
