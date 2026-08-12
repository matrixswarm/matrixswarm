import hashlib
import base64

def _deep_get(d, *paths):
    for p in paths:
        cur = d
        ok = True
        for k in p.split("."):
            if not isinstance(cur, dict) or k not in cur:
                ok = False; break
            cur = cur[k]
        if ok and cur: return cur
    return None

def list_directives_from_vault(vault_data):
    v = (vault_data or {}).get("vault", {})
    out = []
    for dep_id, d in v.get("deployments", {}).items():
        serial = d.get("serial_number", "")
        certs = d.get("certs", {})
        out.append((dep_id, serial, certs))
    return out


_FLATTEN_SUFFIXES = {
    "connection/cert": "https_client_cert",
    "connection/key":  "https_client_key",
    "connection/ca":   "https_ca",
    "signing/remote_pubkey": "remote_pubkey",
    "signing/privkey":       "signing_privkey",  # optional, if you carry it
    # allow simple generic keys too
    "cert": "https_client_cert",
    "key":  "https_client_key",
    "ca":   "https_ca",
}

def normalize_cert_profile(cp: dict = None) -> dict:
    """
    Accepts either:
      - nested machine profile: {https_client_cert, https_client_key, https_ca, remote_pubkey, ...}
      - flattened UI profile:   {"<tag>/connection/cert": "...", ...}
      - generic:                {cert, key, ca}
    Returns a dict with keys the transports expect.
    """
    if not cp:
        return {}

    out = {}
    # Pass-through if already nested
    for k in ("https_client_cert", "https_client_key", "https_ca", "remote_pubkey", "signing_privkey"):
        if cp.get(k):
            out[k] = cp[k]

    # Also map any flattened or generic keys
    for k, v in cp.items():
        for suf, target in _FLATTEN_SUFFIXES.items():
            if k.endswith(suf) and v and target not in out:
                out[target] = v

    return out

def resolve_cert_profile_for_universe(vault_data: dict, universe_id: str) -> dict:
    v = (vault_data or {}).get("vault", {})
    univ = (v.get("universes") or {}).get(universe_id, {})
    bindings = univ.get("bindings", {}) or {}
    registry = v.get("cert_registry", {}) or {}

    prof = {}
    for tag, ver in bindings.items():
        verrec = (registry.get(tag, {}).get("versions") or {}).get(ver, {})
        if not verrec:
            continue

        # normal flattened-by-tag fields
        prof[f"{tag}/connection/cert"] = verrec.get("https_client_cert") or verrec.get("cert")
        prof[f"{tag}/connection/key"]  = verrec.get("https_client_key")  or verrec.get("key")
        prof[f"{tag}/connection/ca"]   = verrec.get("https_ca")          or verrec.get("ca")
        if verrec.get("remote_pubkey"):
            prof[f"{tag}/signing/remote_pubkey"] = verrec["remote_pubkey"]
        spki = verrec.get("spki_pin")
        if spki:
            prof[f"{tag}/connection/spki_pin"] = spki
        # NEW: expose SANs as meta so transports can log them
        sans = verrec.get("sans", {}) or {}
        if sans.get("ip"):
            prof[f"{tag}/meta/sans_ip"] = list(sans["ip"])
        if sans.get("dns"):
            prof[f"{tag}/meta/sans_dns"] = list(sans["dns"])
    return prof



def extract_spki_pin(cert_pem):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization

    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(hashlib.sha256(spki).digest()).decode()

def build_directive_uid_map(vault):
    uid_map = {}
    name_map = {}
    hash_map = {}
    swarm_key_map = {}

    directives = vault.get("directives", {})
    if isinstance(directives, list):
        directives = {str(i): d for i, d in enumerate(directives)}

    for directive_id, directive in directives.items():
        root = directive.get("json", {})
        sec_tag = root.get("security-tag")

        if sec_tag:
            uid_map[sec_tag] = root.get("universal_id")
            name_map[sec_tag] = root.get("name")
            hash_map[sec_tag] = directive.get("directive_hash")
            swarm_key_map[sec_tag] = directive.get("swarm_key")

        for child in root.get("children", []):
            tag = child.get("security-tag")
            uid = child.get("universal_id")
            name = child.get("name")
            if tag and uid:
                uid_map[tag] = uid
            if tag and name:
                name_map[tag] = name

    return uid_map, name_map, hash_map, swarm_key_map


def restructure_cert_profile(tag, versioned_cert):
    cert_block = {}

    conn_cert = versioned_cert.get("cert", "").strip()
    if conn_cert:
        conn_block = {
            "cert": conn_cert,
            "key": versioned_cert.get("key", ""),
            "ca": versioned_cert.get("ca", "")
        }
        try:
            conn_block["spki_pin"] = extract_spki_pin(conn_cert)
        except Exception as e:
            print(f"[WARN] Failed to extract SPKI pin for tag '{tag}': {e}")
        cert_block["connection"] = conn_block

    pubkey = versioned_cert.get("remote_pubkey")
    if pubkey:
        cert_block["signing"] = {
            "remote_pubkey": pubkey
        }
        for opt in ["cn", "sans", "created_at"]:
            if opt in versioned_cert:
                cert_block["signing"][opt] = versioned_cert[opt]

    return cert_block if cert_block else None



def rewrite_vault(vault_data):
    v = vault_data.setdefault("vault", {})
    deployments = v.get("deployments", {}).copy()
    spki_map = v.get("spki_pin_to_cert", {}).copy()

    uid_map, name_map, hash_map, swarm_key_map = build_directive_uid_map(v)

    directives = v.get("directives", {})
    if isinstance(directives, list):
        directives = {str(i): d for i, d in enumerate(directives)}

    for directive_id, directive in directives.items():
        root = directive.get("json", {})
        sec_tag = root.get("security-tag")
        serial = hash_map.get(sec_tag, directive_id)[:12] if sec_tag else directive_id[:12]
        dep_id = f"deployment_{serial}"

        if dep_id in deployments:
            import uuid
            dep_id = f"{dep_id}_{uuid.uuid4().hex[:8]}"

        tag_certs_grouped = {}
        for child in root.get("children", []):
            tag = child.get("security-tag")
            if not tag:
                continue
            certs = child.get("certs", {})
            tag_certs_grouped[tag] = {
                "connection": certs.get("connection", {}),
                "signing": certs.get("signing", {})
            }

        if sec_tag:
            root_certs = root.get("certs", {})
            if root_certs:
                tag_certs_grouped[sec_tag] = {
                    "connection": root_certs.get("connection", {}),
                    "signing": root_certs.get("signing", {})
                }

        agents = []
        for tag, role_block in tag_certs_grouped.items():
            combined_cert_data = {}
            combined_cert_data.update(role_block.get("connection", {}))
            combined_cert_data.update(role_block.get("signing", {}))

            certs = restructure_cert_profile(tag, combined_cert_data)
            if not certs:
                print(f"[SKIP] No usable certs found for tag '{tag}' — skipping agent.")
                continue

            agent_uid = uid_map.get(tag, f"{tag}-agent")
            agent_name = name_map.get(tag, tag)
            agent = {
                "universal_id": agent_uid,
                "name": agent_name,
                "tags": [{
                    "security-tag": {
                        "tag": tag,
                        "certs": certs
                    }
                }]
            }
            agents.append(agent)

            pin = certs.get("connection", {}).get("spki_pin")
            if pin:
                spki_map[pin] = f"{dep_id}/agents/{agent_uid}/tags/{tag}/certs/connection"

        deployments[dep_id] = {
            "label": directive.get("label", "Deployed Directive"),
            "serial_number": serial,
            "directive_hash": directive.get("directive_hash", ""),
            "swarm_key": directive.get("swarm_key", ""),
            "options": {},
            "agents": agents
        }

    v["deployments"] = deployments
    v["spki_pin_to_cert"] = spki_map

    if "connection_groups_to_deployments" not in v or not v["connection_groups_to_deployments"]:
        v["connection_groups_to_deployments"] = {}

    cg2d = v["connection_groups_to_deployments"].copy()
    for group_id, group_def in v.get("connection_groups", {}).items():
        for dep_id, dep in v["deployments"].items():
            tags_present = set()
            for agent in dep.get("agents", []):
                for tag_entry in agent.get("tags", []):
                    tag = tag_entry.get("security-tag", {}).get("tag")
                    if tag:
                        tags_present.add(tag)

            for proto in group_def.keys():
                if proto.startswith("https") and "perimeter_https" in tags_present and group_id not in cg2d:
                    cg2d[group_id] = dep_id
                    break
                elif proto.startswith("wss") and "perimeter_websocket" in tags_present and group_id not in cg2d:
                    cg2d[group_id] = dep_id
                    break
    v["connection_groups_to_deployments"] = cg2d

    return vault_data

def sync_spki_pin_to_cert(vault_data):
    v = vault_data.setdefault("vault", {})
    spki_map = v.setdefault("spki_pin_to_cert", {})
    spki_map.clear()

    for dep_id, dep in (v.get("deployments") or {}).items():
        universe_id = dep.get("universe_id") or dep.get("label") or "unknown_universe"
        agents = dep.get("agents", []) or []

        for agent in agents:
            uid = agent.get("universal_id", "unknown")
            for tag_entry in agent.get("tags", []):
                s_tag = tag_entry.get("security-tag", {})
                tag = s_tag.get("tag", "unknown_tag")
                certs = s_tag.get("certs", {})

                conn = certs.get("connection", False)
                if not conn:
                    print(f"[SKIP] Agent '{uid}' tag '{tag}' has no connection cert — skipping SPKI pin.")
                    continue

                pin = conn.get("spki_pin")
                if pin:
                    spki_map[pin] = f"{dep_id}/agents/{uid}/tags/{tag}/certs/connection"