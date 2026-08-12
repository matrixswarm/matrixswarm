import base64, hashlib, re
from typing import Optional, Dict, Any
from cryptography import x509
from cryptography.hazmat.primitives import serialization
import binascii
SERIAL_RX = re.compile(r"serial_([0-9a-f]+)")

def get_expected_spki(vault_data, serial):
    v = (vault_data or {}).get("vault", {})
    for dep_id, d in v.get("deployments", {}).items():
        if d.get("serial_number") == serial or dep_id == serial:
            # New-scheme
            ph = d.get("certs", {}).get("perimeter_https", {})
            spki = (ph.get("connection", {}) or {}).get("spki_pin")
            if spki:
                return spki
            # Simple layout
            return (d.get("connection_certs") or {}).get("spki_pin")
    return None

def get_https_material(vault_data: Dict[str, Any], serial: str) -> Dict[str, Any]:
    node = ((vault_data or {}).get("vault", {}).get("deployments") or {}).get(serial) or {}
    return (node.get("connection_certs") or {})

# --- migration helpers ---
def _spki_pin_from_pem_cert(cert_pem: str) -> str:
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(hashlib.sha256(spki).digest()).decode()

def _cert_sha256_hex_from_pem(cert_pem: str) -> str:
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()

def pick_deployment_serial(vault_data, host=None, prefer_serial=None):
    v = (vault_data or {}).get("vault", {})
    deps = v.get("deployments") or {}
    if prefer_serial and any(d.get("serial_number") == prefer_serial for d in deps.values()):
        return prefer_serial
    if host:
        for dep_id, d in deps.items():
            # Check new-scheme tag meta
            ph = (d.get("certs", {}).get("perimeter_https", {}) or {}).get("meta", {})
            if host in (ph.get("sans_ip") or []) or host in (ph.get("sans_dns") or []):
                return d.get("serial_number")
            # Check simple layout
            cc_meta = (d.get("connection_certs") or {}).get("sans", {})
            if host in cc_meta.get("ip", []) or host in cc_meta.get("dns", []):
                return dep_id
    if len(deps) == 1:
        return next(iter(deps.values())).get("serial_number") or next(iter(deps.keys()))
    return None

def validate_simple_vault(vault_data: dict) -> None:
    v = (vault_data or {}).get("vault", {})
    deps = v.get("deployments")
    if deps is None:
        raise AssertionError("vault.deployments missing")

    if not isinstance(deps, dict):
        raise AssertionError("vault.deployments is not a dictionary")

    if not deps:
        print("[VAULT][INFO] vault.deployments is empty — allowed for new vaults")
        return  # allow empty deployments at startup

    cur = v.get("deployments_current")

    if cur is not None and cur not in deps:
        raise AssertionError("vault.deployments_current does not match any deployment")

    assert cur in deps, "vault.deployments_current is not a key in deployments"

    if not isinstance(deps, dict) or not deps:
        raise ValueError("vault.deployments missing or empty — vault not initialized?")

    for serial, node in deps.items():
        cc = node.get("connection_certs") or {}
        spki = cc.get("spki_pin"); fp = cc.get("fingerprint_sha256")
        assert spki and isinstance(spki, str), f"{serial}: spki_pin missing"
        assert fp and isinstance(fp, str) and len(fp)==64, f"{serial}: fingerprint_sha256 invalid"
        try:
            base64.b64decode(spki + "==")
            binascii.unhexlify(fp)
        except Exception as e:
            raise AssertionError(f"{serial}: invalid pin/hash: {e}")
