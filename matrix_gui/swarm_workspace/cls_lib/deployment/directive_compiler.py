import hashlib, time, uuid
from copy import deepcopy

class DirectiveCompiler:
    def __init__(self, ir_map, root_gid):
        self.ir = ir_map
        self.root = root_gid

    def compile(self):
        return {"agents": self._build_public_tree(self.root)}

    # Commander Edition — editor-driven directive builder
    def _build_public_tree(self, gid):
        agent_ir = self.ir[gid]
        base_cfg = deepcopy(agent_ir.node.get("config", {}))

        node = {
            "universal_id": agent_ir.universal_id,
            "name": agent_ir.name,
            "serial": agent_ir.node.get("serial"),
            "config": base_cfg,
            "children": []
        }

        node["config"].setdefault("security", {})

        # inject editor public data
        for cname, con in agent_ir.resolved.items():
            editor = getattr(con, "handler", None)
            if not editor:
                continue

            # --- autogen editors: strip private keys ---
            if editor.directive_fields():
                fields = editor.directive_fields()
            else:
                fields = con.fields

            path = editor.get_directory_path()
            if path:
                # drop redundant "config" root if present
                if path[0] == "config":
                    path = path[1:]

                # if path is empty after trimming, write directly under config
                if not path:
                    node["config"].update(fields)
                else:
                    self._set_nested(node["config"], path, fields)

            else:
                node["config"].update(fields)

        # recurse into children
        for child_gid in agent_ir.children:
            node["children"].append(self._build_public_tree(child_gid))

        return node

    def _set_nested(self, base: dict, path_parts: list[str], value):
        """Simple nested setter (replacement for AutoGenConstraint.set_nested)."""
        node = base
        for part in path_parts[:-1]:
            node = node.setdefault(part, {})
        node[path_parts[-1]] = value

    def _sanitize_public(self, data, category=None):
        """
        Commander Edition — lightweight sanitizer.
        Strips accidental secrets (passphrases, remote_privkey, etc.)
        but respects explicit editor directive_fields() outputs.
        """
        if not isinstance(data, dict):
            return data

        clean = {}
        for k, v in data.items():
            key_lower = k.lower()

            # keep explicit privkey fields — editor has allowed them
            if key_lower == "privkey":
                clean[k] = v
                continue

            # remove other sensitive tokens
            if "remote_priv" in key_lower or "pass" in key_lower:
                continue

            clean[k] = self._sanitize_public(v) if isinstance(v, dict) else v

        return clean
