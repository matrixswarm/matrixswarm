import uuid
from copy import deepcopy
from matrix_gui.swarm_workspace.cls_lib.constraint.constraint_resolver import ConstraintResolver


class AgentNode:
    """
    Commander Edition – Unified Agent Model
    Stored in scene, saved to workspace, restored from disk.
    """
    def __init__(self, meta: dict):
        # Static meta.json reference
        self.meta = deepcopy(meta)

        self._constraint_resolver = ConstraintResolver()

        # Identity
        self.name = meta.get("name", "agent")

        self.universal_id = f"{self.name.replace('_', '-')}"
        if not self.name == "matrix":
            self.universal_id = f"{self.universal_id}-{uuid.uuid4().hex[:6]}"

        self.graph_id = uuid.uuid4().hex

        # Structure
        self.parent = None
        self.children = []
        self.connections = []
        self.params = {}
        self.enabled = True
        self.pos = {"x": 0, "y": 0}
        # Capture config section from meta into live node
        cfg = self.meta.get("config", {})
        self.config = deepcopy(cfg) if isinstance(cfg, dict) else {}

        # Constraints
        self.constraints = []
        self._load_default_constraints()
        self._dirty = False

    @classmethod
    def from_saved(cls, meta, saved):
        node = cls(meta)
        node.universal_id = saved.get("universal_id", node.universal_id)
        node.graph_id = saved.get("graph_id", node.graph_id)
        node.parent = saved.get("parent")
        node.children = saved.get("children", [])
        node.connections = saved.get("connections", [])
        node.params = saved.get("params", {})
        node.config = saved.get("config", {})
        node.enabled = saved.get("enabled", True)
        node.pos = saved.get("pos", {"x": 0, "y": 0})
        node.constraints = saved.get("constraints", [])
        return node


    def _load_default_constraints(self):
        defaults = self.meta.get("constraints", [])
        for entry in defaults:
            if not isinstance(entry, dict):
                continue

            cls = list(entry.keys())[0]
            raw = entry[cls] or {}

            is_auto = self._constraint_resolver.is_autogen(cls)
            has_editor = self._constraint_resolver.has_editor(cls)

            if not is_auto and not has_editor:
                raise ValueError(
                    f"[SWARM] Constraint '{cls}' has no autogen handler or editor."
                )

            self.constraints.append({
                "class": cls,
                "raw": raw,
                "serial": None,
                "auto": is_auto,
                "met": is_auto,
                "required": True,
            })

    def get_node(self):
        return {
            "name": self.name,
            "meta": self.meta,
            "config": self.config,
            "universal_id": self.universal_id,
            "graph_id": self.graph_id,
            "parent": self.parent,
            "children": self.children,
            "connections": self.connections,
            "params": self.params,
            "constraints": self.constraints,
            "enabled": self.enabled,
            "pos": self.pos
        }

    # ============================================================
    # ACCESSORS — Commander Edition
    # ============================================================
    def get_graph_id(self):
        return self.graph_id

    def set_graph_id(self, gid: str):
        if not isinstance(gid, str):
            raise ValueError("graph_id must be a string.")
        self.graph_id = gid
        return self

    # --- Identity ---
    def get_name(self):
        return self.name

    def set_name(self, name: str):
        if not name or not isinstance(name, str):
            raise ValueError("AgentNode.name must be a non-empty string.")
        if self.name != name:
            self.name = name
            self.mark_dirty()
        return self

    def get_universal_id(self):
        return self.universal_id

    def set_universal_id(self, uid: str):
        if not isinstance(uid, str):
            raise ValueError("universal_id must be a string.")
        self.universal_id = uid
        return self

    # --- Parent / Child relationships ---
    def get_parent(self):
        return self.parent

    def set_parent(self, parent_uid: str | None):
        if parent_uid is not None and not isinstance(parent_uid, str):
            raise ValueError("parent must be a universal_id string or None.")
        if self.parent != parent_uid:
            self.parent = parent_uid
            self.mark_dirty()
        return self

    def get_children(self):
        return list(self.children)

    def add_child(self, child_uid: str):
        if child_uid not in self.children:
            self.children.append(child_uid)
        return self

    def remove_child(self, child_uid: str):
        if child_uid in self.children:
            self.children.remove(child_uid)
        return self

    # --- Connections ---
    def get_connections(self):
        return list(self.connections)

    def add_connection(self, target_uid: str):
        if target_uid not in self.connections:
            self.connections.append(target_uid)
        return self

    def remove_connection(self, target_uid: str):
        if target_uid in self.connections:
            self.connections.remove(target_uid)
        return self

    # --- Params ---
    def get_param(self, key, default=None):
        return self.params.get(key, default)

    def set_param(self, key, value):
        self.params[key] = value
        return self

    def get_params(self):
        return dict(self.params)

    # --- Enabled flag ---
    def is_enabled(self):
        return self.enabled

    def set_enabled(self, flag: bool):
        self.enabled = bool(flag)
        return self

    # --- Position ---
    def get_position(self):
        return dict(self.pos)

    def set_position(self, x: int, y: int):
        if self.pos["x"] != x or self.pos["y"] != y:
            self.pos["x"] = x
            self.pos["y"] = y
            self.mark_dirty()
            print(f"agent_node.set_position: x={x}, y={y}")
        return self

    # --- Constraints ---
    def get_constraints(self):
        return list(self.constraints)

    def add_constraint(self, name: str, raw=None):
        is_auto = self._constraint_resolver.is_autogen(name)
        has_ed = self._constraint_resolver.has_editor(name)

        if not is_auto and not has_ed:
            raise ValueError(f"[SWARM] Constraint '{name}' cannot be autogen or assigned — no source found.")

        self.constraints.append({
            "class": name,
            "raw": raw or {},
            "serial": None,
            "auto": is_auto,
            "met": is_auto,  # autogen is satisfied automatically
            "required": True,
        })


    def remove_constraint(self, cls_name: str):
        self.constraints = [c for c in self.constraints if c["class"] != cls_name]
        self.mark_dirty()
        return self

    def mark_dirty(self):
        self._dirty = True

    def clear_dirty(self):
        self._dirty = False

    def is_dirty(self):
        return self._dirty

    def all_constraints_met(self):
        for c in self.constraints:
            # required & not autogen must have a serial
            if c.get("required") and not c.get("auto") and not c.get("serial"):
                return False
        return True