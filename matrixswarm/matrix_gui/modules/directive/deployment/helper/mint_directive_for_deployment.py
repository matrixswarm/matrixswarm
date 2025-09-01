def mint_directive_for_deployment(template_directive: dict, wrapped_agents: list, deployment_id: str) -> dict:
    """
    Traverse the template directive and inject config/certs selectively
    using tag-driven mapping rules declared in CERT_INJECTION_MAP.
    If a config already exists in the template, merge into it instead of overwriting.
    """
    from copy import deepcopy
    from matrix_gui.modules.directive.maps.base import CERT_INJECTION_MAP

    agent_map = {w.uid(): w for w in wrapped_agents}

    def set_nested(obj, path: list, key, value):
        for p in path:
            obj = obj.setdefault(p, {})
        obj[key] = value

    def merge_config(dest: dict, src: dict):
        """
        Merge src dict into dest dict. Overwrites scalars,
        merges nested dicts, and preserves other fields.
        """
        for k, v in src.items():
            if v is None:
                continue
            if isinstance(v, dict):
                dest.setdefault(k, {})
                merge_config(dest[k], v)
            else:
                dest[k] = deepcopy(v)

    def patch_node_in_place(node):
        uid = node.get("universal_id")
        if not uid:
            return

        node["deployment_id"] = deployment_id

        wrapper = agent_map.get(uid)
        if not wrapper:
            return

        config_overrides = wrapper.get_config_overrides()

        port = config_overrides.get("port")
        if port is None:
            print(f"[DEPLOYMENT MINT] Agent '{uid}' missing explicit port; port will be left unset.")
        else:
            print(f"[DEPLOYMENT MINT] Injecting port={port} for agent '{uid}'")

        # ensure config block exists in node
        node.setdefault("config", {})

        # merge wrapper overrides into config
        merge_config(node["config"], config_overrides)

        # merge any config provided in tags, then remove it
        tags = wrapper.tags()
        if "config" in tags:
            node.setdefault("config", {})
            merge_config(node["config"], tags["config"])
            # ❌ Remove duplicate to prevent 2nd config showing up
            node["tags"].pop("config", None)

        # handle cert injection as before
        for tag_name, tag_info in CERT_INJECTION_MAP.items():
            if tag_name == "config":
                continue  # config handled separately
            tag_data = tags.get(tag_name)
            if not tag_data:
                continue

            target_path = tag_info["target"]

            if tag_name == "packet_signing":
                signing = wrapper.get_signing()
                for direction, fields in tag_info.get("fields", {}).items():
                    if tag_data.get(direction):
                        for field in fields:
                            val = signing.get(field)
                            if val:
                                set_nested(node, target_path, field, val)
                if tag_info.get("include_serial"):
                    serial = signing.get("serial")
                    if serial:
                        set_nested(node, target_path[:-1], "serial", serial)

            elif tag_name == "connection_cert":
                proto = tag_data.get("proto")
                if proto and proto in tag_info.get("proto_required", []):
                    cert_bundle = wrapper.get_connection_cert() or {}
                    for cert_block, fields in tag_info.get("fields", {}).items():
                        sub = cert_bundle.get(cert_block, {})
                        for field in fields:
                            val = sub.get(field)
                            if val:
                                set_nested(node, target_path + [cert_block], field, val)

        sec_tag = wrapper.get_security_tag()
        if sec_tag:
            node["security-tag"] = sec_tag

        for child in node.get("children", []):
            patch_node_in_place(child)

    directive = deepcopy(template_directive)
    patch_node_in_place(directive)
    return directive


