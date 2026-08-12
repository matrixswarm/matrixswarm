import json, uuid, hashlib, time
from datetime import datetime
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit
from .exceptions.manual_constraint_failure import ManualConstraintFailure
from matrix_gui.swarm_workspace.cls_lib.constraint.constraint_validator import ConstraintValidator
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.swarm_workspace.cls_lib.constraint.constraint_object import Constraint

from .deploy import Deploy
from .agent_ir import AgentIR
from .deployment_compiler import DeploymentCompiler
from .directive_compiler import DirectiveCompiler

# -------------------------------------------------------------
# Deployment Container
# -------------------------------------------------------------
class DualBuilder:
    """Holds Deployment JSON and Directive JSON together."""

    def __init__(self):
        self.deployment = {
            "agents": {},
            "timestamp": datetime.utcnow().isoformat(),
            "certs": {}   # FULL PRIVATE CRYPTO STORE
        }

        self.directive = {
            "agents": {},
            "timestamp": datetime.utcnow().isoformat(),
        }

    def set_root_deployment(self, root):
        self.deployment["agents"] = root

    def set_root_directive(self, root):
        self.directive["agents"] = root

class DeploymentSession:
    def __init__(self, ws, tree, root_uid, resolver):
        """
        tree      = exported agent tree from workspace
        root_uid  = universal_id of the matrix root
        resolver  = ConstraintResolver instance
        """
        self.tree = tree
        self.root_uid = root_uid
        self.resolver = resolver
        self.workspace = ws
        self.dual = DualBuilder()
        self.timestamp = datetime.utcnow()
        self.deployment_id = uuid.uuid4().hex

        # private crypto bundles (signing, certs, AES, etc.)
        self.crypto_store = {}

    # =========================================================
    # ENTRYPOINT
    # =========================================================
    def run(self, workspace_id):
        """
        Commander Edition — streamlined deploy pipeline
        (uses live workspace tree, no reconstruction).
        """
        r = False
        try:
            root_gid = self.root_uid
            if not root_gid:
                print("[DEPLOY][FATAL] No root agent found")
                return self.dual

            # Resolve all constraints directly on the live nodes
            try:
                resolved_constraints = self._resolve_constraints_parallel(self.tree)
            except ManualConstraintFailure as e:
                print(str(e))
                return None

            # Build IR map
            ir_map = {}
            for gid, node in self.tree.items():
                rdict = resolved_constraints.get(gid, {})  # already a dict of Constraint objs
                node['serial'] = str(hashlib.sha256(f"{uuid.uuid4()}-{time.time()}".encode()).hexdigest())
                ir_map[gid] = AgentIR(
                    gid=gid,
                    node=node,
                    resolved_dict=rdict,
                    children=node.get("children", []),
                )

            # Compile deploy + directive
            deploy_compiler = DeploymentCompiler(ir_map, root_gid)
            directive_compiler = DirectiveCompiler(ir_map, root_gid)
            deployment_data = deploy_compiler.compile()
            directive_data = directive_compiler.compile()

            # Fill builder
            flat_agents = self._flatten_agents(deployment_data["agents"])
            self.dual.deployment["agents"] = flat_agents
            self.dual.set_root_directive(directive_data["agents"])


            #self.dump_agents_section(self.dual.deployment)
            #self.dump_certs_section(self.dual.deployment)
            #print(json.dumps(self.dual.directive["agents"], indent=2))

            self.dual.deployment["certs"] = self._normalize_certs(self.dual.deployment.get("certs", {}))

            deploy = Deploy()
            deploy.deploy_directive(self.workspace, directive_data, self.dual, workspace_id)

            r = True

        except Exception as e:
            emit_gui_exception_log("DeploymentSession.run", e)

        return r

    def dump_agents_section(self, deployment_data):
        print("\n====================== AGENTS SECTION ======================")
        print(json.dumps(deployment_data.get("agents", {}), indent=2))
        print("===========================================================\n")

    def dump_certs_section(self, deployment_data):
        print("\n====================== CERTS SECTION =======================")
        print(json.dumps(deployment_data.get("certs", {}), indent=2))
        print("===========================================================\n")

    def _inject_autogen_bundle(self, agent_uid, cname, editor, bundle):
        """
        Commander Edition — places each autogen editor's bundle
        into its proper deployment path using get_deployment_path().
        """
        try:
            path_parts = editor.get_deployment_path(self.tree[agent_uid]["universal_id"])
            if not path_parts or len(path_parts) < 3:
                print(f"[DEPLOY][WARN] {cname} returned invalid deployment path.")
                return

            # Example: ["certs", universal_id, "signing"]
            root, agent_id, leaf = path_parts
            certs_root = self.dual.deployment.setdefault(root, {})
            agent_block = certs_root.setdefault(agent_id, {})
            agent_block[leaf] = bundle
            print(f"[DEBUG][INJECT] {cname} → {path_parts} | bundle keys: {list(bundle.keys())}")

        except Exception as e:
            print(f"[DEPLOY][ERROR] inject_autogen_bundle {cname}: {e}")

    def _extract_crypto_from_constraints(self, resolved):
        """
        Commander Edition — extracts cryptographic constraint bundles from
        resolved editor outputs into a {agent_id: {category: fields}} structure.
        """
        crypto_map = {}

        for gid, constraints in resolved.items():
            agent = self.tree[gid]
            aid = agent["universal_id"]

            for cname, con in constraints.items():
                # detect if this is a crypto-type editor
                if cname in ("packet_signing", "signing", "symmetric_encryption", "connection_cert"):
                    crypto_map.setdefault(aid, {})[cname] = con.fields

        return self._normalize_certs(crypto_map)

    def _normalize_certs(self, certs):
        """
        Commander Edition — normalize certs to contain all three bundles.
        Ensures each agent has connection_cert, signing, and symmetric_encryption.
        """
        normalized = {}
        for aid, bundles in certs.items():
            normalized[aid] = {
                "connection_cert": bundles.get("connection_cert", {}),
                "signing": bundles.get("signing", {}),
                "symmetric_encryption": bundles.get("symmetric_encryption", {})
            }
        return normalized

    def _resolve_constraints_parallel(self, raw_nodes):
        """
        Commander Edition – unified editor resolver.
        Handles autogen and registry editors, writes certs via get_deployment_path(),
        and injects connection fields directly into agents.
        """
        validator = ConstraintValidator()
        resolved = {}

        for gid, agent in raw_nodes.items():
            entries = {}
            valid_agent = True
            constraints = agent.get("constraints", [])

            if not constraints:
                print(f"[VALIDATE][{agent['name']}] ⚠️ No constraints defined.")
                agent["valid"] = False
                continue

            print(f"[DEBUG][VALIDATE_START] {agent['name']} has {len(constraints)} constraints:")

            for c in constraints:
                cname = c["class"]
                editor_cls = self.resolver.get(cname)
                if not editor_cls:
                    if not c.get("auto") and c.get("required"):
                        raise ManualConstraintFailure(
                            f"[DEPLOY BLOCKED] '{agent['name']}' requires '{cname}', but no editor was found."
                        )
                    print(f"[VALIDATE][{agent['name']}:{cname}] ⚠️ Missing editor.")
                    valid_agent = False
                    continue

                try:
                    editor = editor_cls() if isinstance(editor_cls, type) else editor_cls
                    is_auto = hasattr(editor, "is_autogen") and editor.is_autogen()

                    # --- Validate registry constraint ---
                    if not is_auto and c.get("serial"):
                        ok, msg = validator.validate(c)
                        if not ok:
                            print(f"[VALIDATE][{agent['name']}:{cname}] ❌ {msg}")
                            valid_agent = False
                            continue
                        print(f"[VALIDATE][{agent['name']}:{cname}] ✅ {msg}")

                    # --- Resolve bundle ---
                    if is_auto:
                        result = editor.deploy_fields()
                        # immediately place it where it belongs
                        self._inject_autogen_bundle(gid, cname, editor, result)

                    elif c.get("serial"):
                        try:
                            reg_store = self.resolver.vcs.get_store("registry")
                            ns = reg_store.get_namespace(cname)
                            obj = ns.get(c["serial"], {})
                            editor._load_data(obj)
                            result = editor.deploy_fields()
                        except Exception as e:
                            print(f"[RESOLVE][WARN] Registry fetch failed for {cname}: {e}")
                            result = {}
                    else:
                        raise ValueError(
                            f"[VALIDATE][{agent['name']}:{cname}] Unresolved: Constraint is missing both 'serial' and 'autogen'."
                        )

                    if not result:
                        print(f"[RESOLVE][WARN] Empty result from {cname}")
                        continue

                    # --- Store constraint object ---

                    con = Constraint(cname, editor, c, agent)
                    con.fields = result
                    entries[cname] = con
                    print(f"[RESOLVE][OK] {agent['name']}:{cname} ✓")

                except Exception as e:
                    print(f"[RESOLVE][ERROR] {agent['name']}:{cname} → {e}")
                    raise ValueError(
                        f"[VALIDATE][{agent['name']}:{cname}] {e}."
                    )

            # --- Inject connection fields ---
            agent_conn = {}
            for cname, con in entries.items():
                try:
                    ed = con.handler if hasattr(con, "handler") else None
                    ed = ed or (self.resolver.get(cname)() if isinstance(self.resolver.get(cname), type) else None)
                    if ed and hasattr(ed, "is_connection") and ed.is_connection():
                        agent_conn.update(con.fields)
                except Exception as e:
                    print(f"[CONNECTION][WARN] {agent['name']}:{cname} → {e}")

            if agent_conn:
                agent["connection"] = agent_conn
                print(f"[CONNECTION][OK] Injected connection fields for {agent['name']}")

            agent["valid"] = valid_agent
            resolved[gid] = entries

        return resolved

    def _flatten_agents(self, root):
        """Return a flat list of all agents in the deployment tree."""
        flat = []

        def recurse(node):
            # Skip invalid nodes
            if not node or not isinstance(node, dict):
                return

            flat.append({
                "universal_id": node.get("universal_id"),
                "name": node.get("name"),
                "serial": node.get("serial"),
                "security-tag": node.get("security-tag"),
                "config": node.get("config", {}),
                "connection": node.get("connection", {})
            })

            for child in node.get("children", []):
                recurse(child)

        # root may be a list or a single dict
        if isinstance(root, list):
            for n in root:
                recurse(n)
        else:
            recurse(root)

        return flat


    # =========================================================
    # 3) CONFIG SYNTHESIZER (FIELD MERGER)
    # =========================================================
    def _synthesize_agent_config(self, agent):
        """
        Combines resolved constraints + params + registry
        into final Phoenix-style config.
        """

        cfg = {}
        sec = cfg.setdefault("security", {})

        for cname, entry in agent["resolved_constraints"].items():
            cat = entry["category"]
            full = entry["full"]

            if cat == "signing":
                sec.setdefault("signing", {}).update(full)

            elif cat == "symmetric_encryption":
                sec.setdefault("symmetric_encryption", {}).update(full)

            elif cat == "connection":
                sec.setdefault("connection", {}).update(full)

        # Merge runtime agent params into config
        if agent.get("params"):
            cfg.update(agent["params"])

        return cfg

    # =========================================================
    # 4) BUILD DEPLOYMENT NODE (PRIVATE CONFIG)
    # =========================================================
    def _build_deployment(self, graph_id):
        """
        Uses graph_id relationships to produce full hierarchical deployment.
        """

        agent = self.tree[graph_id]

        # Build node structure
        node = {
            "universal_id": agent["universal_id"],
            "name": agent["name"],
            "serial": agent.get("serial"),
            "security-tag": agent.get("security-tag"),
            "config": self._synthesize_agent_config(agent),
            "children": []
        }

        # Inject connection block if this agent has one
        node["connection"] = agent.get("connection", {})

        # Fallback: if not yet stored on agent, check for connection editors
        if not node["connection"]:
            for cname, entry in agent.get("resolved_constraints", {}).items():
                try:
                    editor_cls = self.resolver.get(cname)
                    if editor_cls:
                        editor = editor_cls() if isinstance(editor_cls, type) else editor_cls
                        if hasattr(editor, "is_connection") and editor.is_connection():
                            node["connection"] = entry.fields
                            break
                except Exception as e:
                    print(f"[DEPLOY][WARN] Connection injection failed for {agent['name']}:{cname} → {e}")

        # Recursively process all children dynamically
        for child_gid in self._get_children(graph_id):
            node["children"].append(self._build_deployment(child_gid))

        return node

    def _get_children(self, gid):
        """Yield all child graph_ids whose parent == gid."""
        return [cid for cid, n in self.tree.items()
                if n.get("parent") == gid]

    # =========================================================
    # 5) BUILD DIRECTIVE NODE (PUBLIC CONFIG)
    # =========================================================
    def _build_directive(self, graph_id):
        """
        Commander Edition – Recursive public config builder.
        Mirrors the deployment tree but keeps only public slices.
        """

        agent = self.tree[graph_id]

        # BASE CONFIG from meta
        base_cfg = {}
        meta_cfg = agent.get("meta", {}).get("config", {})

        if isinstance(meta_cfg, dict):
            base_cfg = json.loads(json.dumps(meta_cfg))  # deep copy

        node = {
            "universal_id": agent["universal_id"],
            "name": agent["name"],
            "config": base_cfg,
            "children": []
        }

        sec = node["config"].setdefault("security", {})

        for cname, entry in agent.get("resolved_constraints", {}).items():
            cat = entry["category"]
            slice_ = entry["slice"]

            if cat == "signing":
                sec.setdefault("signing", {}).update(slice_)
            elif cat == "symmetric_encryption":
                sec.setdefault("symmetric_encryption", {}).update(slice_)
            elif self.resolver.is_connection(cname):
                # connections are not part of directive for security
                continue
            elif cat == "connection":
                sec.setdefault("connection", {}).update(slice_)

        # Dynamically traverse children via parent relationships
        for child_gid in self._get_children(graph_id):
            node["children"].append(self._build_directive(child_gid))

        return node

# -------------------------------------------------------------
# Simple GUI popup to visualize results
# -------------------------------------------------------------
class DeploymentViewer(QDialog):
    def __init__(self, builder, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Commander Deployment Objects")
        self.setMinimumWidth(900)
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        layout.addLayout(top)

        self.deployment_text = QTextEdit()
        self.deployment_text.setReadOnly(True)
        self.deployment_text.setStyleSheet("color:#00ff88; background:#111;")
        top.addWidget(self.deployment_text)

        self.directive_text = QTextEdit()
        self.directive_text.setReadOnly(True)
        self.directive_text.setStyleSheet("color:#ffaa00; background:#111;")
        top.addWidget(self.directive_text)

        self.refresh(builder)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def refresh(self, builder):
        self.deployment_text.setText(json.dumps(builder.deployment, indent=2))
        self.directive_text.setText(json.dumps(builder.directive, indent=2))
