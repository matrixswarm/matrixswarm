from copy import deepcopy

# --- KISS defaults (edit as you like)
_DEFAULT_SERVICE_MANAGER = [
    {
        "role": [
            "hive.alert.send_alert_msg",
            "hive.rpc.route",
            "hive.log.delivery",
        ],
        "scope": ["parent", "any"],
        "priority": {
            "hive.log.delivery": -1,
            "hive.proxy.route": 5,
            "default": 10,
        },
        "exclusive": False,
    }
]

def _derive_security_tag_from_proto(proto: str) -> str:
    """
    Map connection proto -> security-tag name.
    https -> perimeter_https
    wss/ws -> perimeter_websocket
    anything else -> perimeter_<proto>
    """
    if proto in ("wss", "ws"):
        return "perimeter_websocket"
    return f"perimeter_{proto}"

def _bool_tag_enabled(tags_dict: dict, tag_key: str) -> bool:
    """
    Helper for tags like:
      "packet_signing": {"in": True, "out": True}
    """
    t = (tags_dict or {}).get(tag_key)
    if isinstance(t, dict):
        return any(bool(v) for v in t.values())
    return bool(t)

def _extract_connection_tag(tags_dict: dict) -> dict:
    """
    Expecting shapes like:
      "connection": {"proto": "wss", "spki_pin_auth": True}
    """
    conn = (tags_dict or {}).get("connection") or {}
    return dict(conn)

def _make_base_agent(node: dict, agent_row: dict | None) -> dict:
    """
    Seed the agent shell from template node + aggregator row.
    """
    out = {
        "universal_id": node.get("universal_id"),
        "name": node.get("name"),
        # security-tag set later if a connection tag exists
        "config": {
            "port": agent_row.get("port") if agent_row else None,
            "allowlist_ips": agent_row.get("allowlist_ips", []) if agent_row else [],
            "service-manager": deepcopy(agent_row.get("service-manager", _DEFAULT_SERVICE_MANAGER)) if agent_row else deepcopy(_DEFAULT_SERVICE_MANAGER),
            # security added below
        },
        # tags are not emitted in deployment agent objects; we mint concrete security
    }
    # Clean None port if not provided
    if out["config"]["port"] is None:
        out["config"].pop("port", None)
    return out

def _apply_signing_block(agent_obj: dict, creds: dict | None, want_signing: bool) -> None:
    """
    Attach signing block under config.security.signing with both remote_pubkey and privkey.
    'creds' may look like:
      {
        "signing": {
          "remote_pubkey": "...PEM...",
          "privkey": "...PEM...",
          "serial": "abcd1234"
        }
      }
    """
    if not want_signing:
        return
    signing_creds = ((creds or {}).get("signing")) or {}
    if not signing_creds:
        # Nothing to attach; still create the slot if you want strict structure
        agent_obj.setdefault("config", {}).setdefault("security", {})["signing"] = {}
        return

    sec = agent_obj.setdefault("config", {}).setdefault("security", {})
    sec["signing"] = {
        # required by your directive: both keys present when signing is enabled
        "remote_pubkey": signing_creds.get("remote_pubkey"),
        "privkey": signing_creds.get("privkey"),
    }
    # serial at the same level as signing/connection (matches your example)
    serial = signing_creds.get("serial")
    if serial:
        sec["serial"] = serial

def _apply_connection_block(agent_obj: dict, conn_tag: dict, creds: dict | None) -> None:
    """
    Attach connection security (cert/key/ca and optional spki_pin).
    'creds' may look like:
      {
        "connection": {
          "cert": "...PEM...",
          "key": "...PEM...",
          "ca":  "...PEM...",
          "spki_pin": "base64=="
        }
      }
    """
    if not conn_tag:
        return

    proto = conn_tag.get("proto")
    if proto:
        agent_obj["security-tag"] = _derive_security_tag_from_proto(proto)

    conn_creds = ((creds or {}).get("connection")) or {}
    sec = agent_obj.setdefault("config", {}).setdefault("security", {})
    sec_conn = sec.setdefault("connection", {})

    for k in ("cert", "key", "ca"):
        if k in conn_creds:
            sec_conn[k] = conn_creds[k]

    # Only include spki_pin if template wants pin auth AND we have one
    if conn_tag.get("spki_pin_auth") and "spki_pin" in conn_creds:
        sec_conn["spki_pin"] = conn_creds["spki_pin"]

def _walk_template_nodes(root: dict):
    """
    Yield each node in the template directive (preorder).
    """
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        for child in reversed(node.get("children", []) or []):
            stack.append(child)

def mint_deployment_agents(template_directive: dict,
                           agent_aggregator: dict,
                           creds_by_uid: dict) -> dict:
    """
    Build the 'agents' array for deployment from:
      - template_directive (from phoenix-01.py)  ← structure & tags:contentReference[oaicite:2]{index=2}
      - agent_aggregator (per-agent overrides like port, allowlist, service-manager)
      - creds_by_uid (PEMs and pins for signing/connection)
    Ensures the top-level 'matrix' is included.
    Returns: {"agents": [ ... ]}
    """
    agents = []
    seen = set()

    for node in _walk_template_nodes(template_directive):
        uid = node.get("universal_id")
        if not uid:
            continue

        # Collect tag info
        tags_dict = node.get("tags") or {}
        want_signing = _bool_tag_enabled(tags_dict, "packet_signing")
        conn_tag = _extract_connection_tag(tags_dict)  # {} if none

        # Aggregator row & creds
        agg_row = (agent_aggregator or {}).get(uid, {})
        creds = (creds_by_uid or {}).get(uid, {})

        # Assemble agent
        agent_obj = _make_base_agent(node, agg_row)
        _apply_signing_block(agent_obj, creds, want_signing)
        _apply_connection_block(agent_obj, conn_tag, creds)

        agents.append(agent_obj)
        seen.add(uid)

    # Safety: If for any reason 'matrix' wasn’t in template, synthesize it
    if "matrix" not in seen:
        node = {"universal_id": "matrix", "name": "matrix", "tags": {"packet_signing": {"in": True, "out": True}}}
        agg_row = (agent_aggregator or {}).get("matrix", {})
        creds = (creds_by_uid or {}).get("matrix", {})
        agent_obj = _make_base_agent(node, agg_row)
        _apply_signing_block(agent_obj, creds, True)
        agents.append(agent_obj)

    return {"agents": agents}
