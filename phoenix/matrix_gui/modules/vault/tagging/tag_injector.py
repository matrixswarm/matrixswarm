import uuid
from copy import deepcopy
from datetime import datetime
from typing import Dict, Any, Tuple
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key
import hashlib
from cryptography import x509
from matrix_gui.modules.vault.crypto.cert_factory import manufacture_cert_set_for_tags, spki_pin_from_pem

def _pick_conn_for_agent(agent: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    for tag in agent.get("tags", []):
        ct = tag.get("connection-tag")
        if ct and ct.get("tag"):
            return ct["tag"], deepcopy(ct)
    return "", {}

def _gen_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()
    ).decode()
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return priv, pub

def _mint_signing_only(tag: str, uid: str) -> Dict[str, Any]:
    priv, pub = _gen_keypair()
    rpriv, rpub = _gen_keypair()
    return {
        "security-tag": {
            "tag": tag,
            "certs": {
                "signing": {
                    "privkey": priv,
                    "pubkey": pub,
                    "remote_privkey": rpriv,
                    "remote_pubkey": rpub,
                    "serial": f"serial_{uuid.uuid4().hex[:8]}",
                    "created_at": datetime.utcnow().isoformat() + "Z"
                }
            }
        }
    }

def _mint_security_tag(tag: str, agent_id: str, conn: Dict[str, Any]) -> Dict[str, Any]:
    """
    Forge certs for the given tag + connection; return a ready-to-attach security-tag.
    Always ensures full key pairs (priv/pub and remote_priv/remote_pub).
    """

    import ipaddress
    ip_sans, dns_sans = [], []
    host = conn.get("host") or conn.get("hostname") or ""
    if host:
        try:
            ipaddress.ip_address(host.strip())
            ip_sans = [host.strip()]
        except ValueError:
            dns_sans = [host.strip()]

    base_tag = tag
    if "websocket" in tag.lower():
        base_tag = "perimeter_websocket"
    elif "https" in tag.lower():
        base_tag = "perimeter_https"
    elif "queen" in tag.lower():
        base_tag = "queen"

    profile_map, serial = manufacture_cert_set_for_tags(
        {base_tag},
        sans_map={base_tag: {"ip": ip_sans, "dns": dns_sans}}
    )
    p = profile_map.get(base_tag, {}) or {}

    # --- Fix signing keypairs ---
    if p.get("privkey"):
        try:
            key = load_pem_private_key(p["privkey"].encode(), password=None)
            pub_bytes = key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo
            )
            if not p.get("pubkey"):
                p["pubkey"] = pub_bytes.decode()
        except Exception:
            pass

    # --- Fix remote keypairs ---
    if not p.get("remote_privkey") or not p.get("remote_pubkey"):
        rpriv, rpub = _gen_keypair()
        p["remote_privkey"] = rpriv
        p["remote_pubkey"] = rpub

    # --- Fingerprint ---
    cert_pem = (
        p.get("cert") or p.get("https_client_cert") or p.get("ca") or ""
    )
    fingerprint = compute_fingerprint(cert_pem)
    if not fingerprint and p.get("pubkey"):
        digest = hashlib.sha256(p["pubkey"].encode()).digest()
        fingerprint = ":".join(f"{b:02X}" for b in digest)

    cert = {
        "cert": cert_pem,
        "key": p.get("key") or p.get("https_client_key") or "",
        "ca": p.get("ca") or p.get("https_ca") or "",
        "cn": f"{tag}-{agent_id}-serial_{(p.get('serial') or serial or '')}".strip("-_"),
        "sans": {"ip": ip_sans, "dns": dns_sans},
        "fingerprint_sha256": fingerprint,
        "spki_pin": spki_pin_from_pem(cert_pem),
        "created_at": datetime.utcnow().isoformat() + "Z",
        "serial": p.get("serial") or serial or uuid.uuid4().hex[:8],
    }

    sec = {
        "tag": tag,
        "certs": {
            "signing": {
                "privkey": p.get("privkey", ""),
                "pubkey": p.get("pubkey", ""),
                "remote_privkey": p.get("remote_privkey", ""),
                "remote_pubkey": p.get("remote_pubkey", ""),
                "serial": cert["serial"],
            }
        }
    }

    if "queen" not in tag.lower():
        sec["certs"]["connection"] = cert

    return {"security-tag": sec}


def inject_all_tags_into_deployment(directive: Dict[str, Any]) -> None:
    target = directive["json"] if "json" in directive else directive

    # Clearly flatten and inject tags once
    target["agents"] = flatten_and_inject_agents(target)

    # Clearly remove 'children' and root-specific keys explicitly
    for key in ["children", "universal_id", "name", "security-tag", "tags", "config"]:
        target.pop(key, None)



def compute_fingerprint(cert_pem: str) -> str:
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        fp = cert.fingerprint(hashlib.sha256())
        return ":".join(f"{b:02X}" for b in fp)
    except Exception:
        return ""

def flatten_and_inject_agents(root: dict) -> list:
    flat_agents = []

    def walk(node):
        agent = dict(node)  # deep copy of agent node
        agent.pop("children", None)
        agent.pop("config", None)

        uid = agent.get("universal_id") or agent.get("name")

        existing_tags = agent.get("tags", []) or []

        preserved_tags = []
        conn_tag = None
        for t in existing_tags:
            if "connection-tag" in t:
                preserved_tags.append(t)
                conn_tag = t["connection-tag"]
            elif "security-tag" not in t:
                preserved_tags.append(t)

        # Determine tagname + connection info
        tagname = agent.get("security-tag") or (
            "queen" if agent.get("name") == "matrix" else None
        )
        if not tagname and conn_tag:
            tagname = conn_tag.get("tag")

        if agent.get("security-tag") == "queen" or agent.get("name") == "matrix":
            sec = _mint_signing_only("queen", uid)
        elif tagname:
            # 🛰 Use connection info if available
            conn_info = conn_tag.get("connection-1") if conn_tag else {}
            sec = _mint_security_tag(tagname, uid, conn_info)
        else:
            sec = None

        if sec:
            preserved_tags.append(sec)

        agent["tags"] = preserved_tags

        flat_agents.append(agent)

        for child in node.get("children", []):
            walk(child)

    walk(root)
    return flat_agents