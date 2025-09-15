from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

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

        try:
            for k, v in src.items():
                if v is None:
                    continue
                if isinstance(v, dict):
                    dest.setdefault(k, {})
                    merge_config(dest[k], v)
                elif isinstance(v, list):
                    # Don’t overwrite non-empty list with an empty one
                    if not v and k in dest:
                        continue
                    dest[k] = v[:]
                else:
                    dest[k] = deepcopy(v)
        except Exception as e:
            emit_gui_exception_log("mint_directive_for_deployment.merge_config", e)


    def patch_node_in_place(node):

        try:
            uid = node.get("universal_id")
            if not uid:
                return

            node["deployment_id"] = deployment_id

            wrapper = agent_map.get(uid)
            if not wrapper:
                return

            node['serial'] = wrapper.get_serial()
            node.setdefault("config", {})
            config_overrides = wrapper.get_config_overrides() or {}

            allowlist = config_overrides.get("allowlist_ips")
            if allowlist is not None:
                if allowlist:
                    print(f"[DEPLOYMENT MINT] Injecting allowlist_ips={allowlist} for agent '{uid}'")
                else:
                    print(f"[DEPLOYMENT MINT] Agent '{uid}' has empty allowlist_ips (no restrictions).")

            if "allowlist_ips" in config_overrides:
                print(f"[DEPLOYMENT MINT] Injecting allowlist_ips={config_overrides['allowlist_ips']} for agent '{uid}'")



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
                if tag_name == "packet_signing":
                    target_path = tag_info["target"]
                    signing = wrapper.get_signing()
                    for direction, fields in tag_info.get("fields", {}).items():
                        if tag_data.get(direction):
                            for field in fields:
                                val = signing.get(field)
                                if val:
                                    set_nested(node, target_path, field, val)
                    #if tag_info.get("include_serial"):
                    #    serial = signing.get("serial")
                    #    if serial:
                    #        set_nested(node, target_path[:-1], "serial", serial)

                elif tag_name == "connection_cert":
                    target_path = tag_info["target"]
                    proto = tag_data.get("proto")
                    if proto and proto in tag_info.get("proto_required", []):
                        cert_bundle = wrapper.get_connection_cert() or {}
                        for cert_block, fields in tag_info.get("fields", {}).items():
                            sub = cert_bundle.get(cert_block, {})
                            for field in fields:
                                val = sub.get(field)
                                if val:
                                    set_nested(node, target_path + [cert_block], field, val)

                elif tag_name == "connection":
                    proto = tag_data.get("proto")
                    if not proto:
                        continue
                    conn_rules = tag_info.get(proto)
                    if not conn_rules:
                        continue
                    target_path = conn_rules.get("target", [])
                    # Pull from organized connection_info if present
                    conn_info = wrapper.agent.get_item("connection_info") or {}
                    conn_details = conn_info.get("details", {})
                    for field in conn_rules.get("fields", []):
                        val = conn_details.get(field) or tag_data.get(field)
                        if val is not None:
                            set_nested(node, target_path, field, val)

            #sec_tag = wrapper.get_security_tag()
            #if sec_tag:
            #    node["security-tag"] = sec_tag

            for child in node.get("children", []):
                patch_node_in_place(child)

        except Exception as e:
            emit_gui_exception_log("mint_directive_for_deployment.patch_node_in_place", e)

    directive = deepcopy(template_directive)
    patch_node_in_place(directive)

    return directive


