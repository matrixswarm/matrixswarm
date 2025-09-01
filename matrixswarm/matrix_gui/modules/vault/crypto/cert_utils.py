import os
import tempfile
import hashlib
import base64
from typing import Dict, Tuple, List

def inject_all_agents_security(tree, cert_profile, serial=None):
    if isinstance(tree, dict):
        if "security-tag" in tree:
            inject_security_by_tag(tree, cert_profile, serial)
        for v in tree.values():
            inject_all_agents_security(v, cert_profile, serial)
    elif isinstance(tree, list):
        for item in tree:
            inject_all_agents_security(item, cert_profile, serial)

def inject_security_by_tag(agent, cert_profile, serial=None):
    """
    Accepts the new FLATTENED profile and maps it to the legacy security block:
      connection: {cert,key,ca}
      signing:    {privkey,remote_pubkey}   (if present)
      serial:     <from profile or fallback>
    """
    config = agent.get("config", {})
    tag = agent.get("security-tag")
    if not tag:
        return

    # Slice flattened keys → per-tag fields
    tag_profile = {
        "cert":         cert_profile.get(f"{tag}/connection/cert"),
        "key":          cert_profile.get(f"{tag}/connection/key"),
        "ca":           cert_profile.get(f"{tag}/connection/ca"),
        "remote_pubkey": cert_profile.get(f"{tag}/signing/remote_pubkey"),
        "serial":        cert_profile.get(f"{tag}/connection/serial"),
        "privkey":       cert_profile.get(f"{tag}/signing/privkey"),
        "spki_pin":      cert_profile.get(f"{tag}/connection/spki_pin"),
    }

    security_block = {}

    # Signing (optional)
    if tag_profile.get("privkey") or tag_profile.get("remote_pubkey"):
        signing_block = {}
        if tag_profile.get("privkey"):
            signing_block["privkey"] = tag_profile["privkey"]
        if tag_profile.get("remote_pubkey"):
            signing_block["remote_pubkey"] = tag_profile["remote_pubkey"]
        if signing_block:
            security_block["signing"] = signing_block

    # Connection (mTLS)
    connection_block = {k: tag_profile[k] for k in ("cert", "key", "ca") if tag_profile.get(k)}
    if connection_block:
        security_block["connection"] = connection_block

    if tag_profile.get("spki_pin"):
        security_block.setdefault("connection", {})
        security_block["connection"]["spki_pin"] = tag_profile["spki_pin"]


    # Serial (optional, keep for continuity)
    the_serial = tag_profile.get("serial") or serial
    if the_serial:
        security_block["serial"] = the_serial

    if security_block:
        config.setdefault("security", {})
        # overwrite with the freshly resolved block
        config["security"] = security_block
        agent["config"] = config

def embed_agent_sources(directive, base_path=None):
    if isinstance(directive, dict):
        agent_name = directive.get("name")
        src_path = directive.get("src")
        if not src_path and agent_name and base_path:
            test_path = os.path.join(base_path, "agent", agent_name, f"{agent_name}.py")
            if os.path.exists(test_path):
                src_path = test_path
                directive["src"] = test_path

        if src_path and os.path.exists(src_path):
            with open(src_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode()
            directive["src_embed"] = encoded

        for v in directive.values():
            embed_agent_sources(v, base_path=base_path)
    elif isinstance(directive, list):
        for item in directive:
            embed_agent_sources(item, base_path=base_path)

def set_hash_bang(directive, base_path=None):
    if isinstance(directive, dict):
        agent_name = directive.get("name")
        src_path = directive.get("src")
        if not src_path and agent_name and base_path:
            test_path = os.path.join(base_path, "agent", agent_name, f"{agent_name}.py")
            if os.path.exists(test_path):
                src_path = test_path
        if "src_embed" in directive:
            src_bytes = base64.b64decode(directive["src_embed"])
            directive["hash_bang"] = hashlib.sha256(src_bytes).hexdigest()
        elif src_path and os.path.exists(src_path):
            with open(src_path, "rb") as f:
                directive["hash_bang"] = hashlib.sha256(f.read()).hexdigest()
        for v in directive.values():
            set_hash_bang(v, base_path=base_path)
    elif isinstance(directive, list):
        for item in directive:
            set_hash_bang(item, base_path=base_path)


