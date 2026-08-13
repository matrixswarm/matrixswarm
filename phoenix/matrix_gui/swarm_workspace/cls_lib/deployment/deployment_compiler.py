from ..constraint.autogen_constraint import AutoGenConstraint
from matrix_gui.swarm_workspace.cls_lib.constraint.constraint_object import Constraint
class DeploymentCompiler:

    def __init__(self, ir_map, root_gid):
        self.ir = ir_map
        self.root = root_gid
        self.certs = {}   # uid → signing/symmetric/connection_cert bundles

    def compile(self):
        agents_section = self._build_private_tree(self.root)
        return {
            "agents": agents_section,
            "certs": self.certs,
        }

    def _build_private_tree(self, gid):
        agent_ir = self.ir[gid]
        node = {
            "universal_id": agent_ir.universal_id,
            "name": agent_ir.name,
            "serial": agent_ir.node.get("serial"),
            "security-tag": agent_ir.node.get("security-tag"),
            "config": {},
            "children": []
        }

        #if(agent_ir.name=="matrix_email"):
        #    print(agent_ir.node)

        # Commander Edition – integrate autogen certs and preserve connections
        node["connection"] = agent_ir.node.get("connection", {})  # keep what we already have

        for con in agent_ir.resolved.values():
            try:

                if not isinstance(con, Constraint):
                    print('not a constraint')
                    continue

                # Preserve existing connection block instead of overwriting
                try:

                    #now we inject the connection details into the deployment
                    editor=con.get_editor()
                    if editor.is_connection():
                        node["connection"].update(con.get_fields())
                        continue

                    #this is a special case, that allows constraint that isn't
                    #a connection to be injected into the deployment, e.g. matrix_email;
                    elif con.inject_into_connection():
                        node["connection"].update(con.get_fields())

                except Exception as e:
                    print(f"{con.get_constraint_name()} has no handler {e}")
                    pass

                # Route certs & crypto bundles into certs section
                base = self.certs.setdefault(agent_ir.universal_id, {})
                if hasattr(con, "path") and con.path:
                    AutoGenConstraint.set_nested(base, con.path, con.get_fields())
                else:
                    base.update(con.get_fields())

            except Exception as e:
                print(f"[DEPLOY][WARN] Connection/cert injection error for {agent_ir.name}: {e}")

        for child_gid in agent_ir.children:
            node["children"].append(self._build_private_tree(child_gid))

        return node

    # -----------------------------
    def _private_security(self, agent_ir):
        cfg = {}
        sec = cfg.setdefault("security", {})
        for cir in agent_ir.resolved.values():
            if cir.category in ("signing", "symmetric_encryption"):
                sec.setdefault(cir.category, {}).update(cir.full)
        return cfg
