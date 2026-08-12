# Commander Edition – Converts old workspace nodes to new schema

import uuid

def migrate_node_to_new_schema(node, meta):
    """
    Upgrades any legacy agent node into the proto-free,
    Commander Edition constraint schema.
    """

    # ---------------------------------------------------------
    # universal_id / meta
    # ---------------------------------------------------------
    if "universal_id" not in node or not isinstance(node["universal_id"], str):
        node["universal_id"] = str(uuid.uuid4())[:8]

    if "meta" not in node or not node.get("meta"):
        node["meta"] = meta

    # ---------------------------------------------------------
    # capture config section from meta
    # ---------------------------------------------------------
    if "meta" not in node or not node.get("meta"):
        node["meta"] = meta

    # capture config section directly into node
    config = (meta or {}).get("config", {})
    if config:
        node["config"] = config
    node.setdefault("config", {})

    # ---------------------------------------------------------
    # params normalized
    # ---------------------------------------------------------
    params = node.get("params", {})
    node["params"] = params if isinstance(params, dict) else {}

    # ---------------------------------------------------------
    # parent normalized
    # ---------------------------------------------------------
    if not node.get("parent"):
        node["parent"] = None

    # ---------------------------------------------------------
    # legacy garbage removal
    # ---------------------------------------------------------
    for k in ["proto", "proto_cdn", "proto_extra",
              "connection_info", "connection_info_cdn",
              "connection_info_extra"]:
        node.pop(k, None)

    # ---------------------------------------------------------
    # MIGRATE TAGS → CONSTRAINTS
    # ---------------------------------------------------------
    migrate_tags_to_constraints(node)

    # ---------------------------------------------------------
    # Ensure new Commander schema fields
    # ---------------------------------------------------------
    node.setdefault("constraints", [])
    node.setdefault("enabled", True)
    node.setdefault("children", [])
    node.setdefault("params", {})

    return node


def migrate_tags_to_constraints(node):
    """
    Convert legacy tags:
        {"connection":{"proto":"wss"}, "packet_signing":{...}, ...}

    Into proto-free constraints:
        [{"wss"}, {"packet_signing": {...}}, {"https"}, ...]
    """

    tags = node.get("tags")
    if not isinstance(tags, dict):
        node.pop("tags", None)
        return node

    constraints = []

    for key, value in tags.items():

        # Case 1 — legacy connection or connection_cert
        # extract proto → becomes {"wss"} or {"https"}
        if isinstance(value, dict) and "proto" in value:
            constraint_key = value["proto"].lower()
            constraints.append({constraint_key: None})
            continue

        # Case 2 — parametric agent-specific configs
        if isinstance(value, dict):
            constraints.append({key.lower(): value})
            continue

        # Case 3 — boolean/flag values
        constraints.append({key.lower(): None})

    # Write new constraints
    node["constraints"] = constraints

    # Remove legacy block
    node.pop("tags", None)

    return node
