# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
from copy import deepcopy
from .vault_store_base import VaultStore

class DeploymentStore(VaultStore):
    def __init__(self, root_vault):
        super().__init__(root_vault, "deployments")

    def allow_delete(self, dep_id):
        # Never delete the core Matrix deployment
        return dep_id != "matrix"

    def validate_key(self, dep_id, cfg):
        """
        Ensure a deployment entry:
            • is a dict
            • has a label
            • has an agents list
        Extend as needed — but keep it simple and defensive.
        """
        return (
            isinstance(cfg, dict)
            and isinstance(dep_id, str)
            and "label" in cfg
            and "agents" in cfg
        )

    def get_dep(self, dep_id, default=None):
        """
        Safe lookup for a deployment entry.
        Returns a deep copy of deployments[dep_id] or a default ({} by default).
        """
        data = self.get_data() or {}
        dep = data.get(dep_id, default if default is not None else {})
        return deepcopy(dep)

    def validate_store(self):
        """
        Validate entire deployments store.
        Run before commit() automatically in VaultStore.
        """
        data = self.get_data()
        if not isinstance(data, dict):
            return False

        for dep_id, cfg in data.items():
            if not self.validate_key(dep_id, cfg):
                print(f"[DEPLOYMENTS][VALIDATION] ❌ Deployment '{dep_id}' invalid.")
                return False

        return True

    def _validate_agent_graph(self, dep_meta):
        agents = dep_meta.get("agents", [])
        if not agents:
            return False

        # Must have exactly one root node (matrix or primary)
        roots = [a for a in agents if not a.get("parent")]
        if len(roots) != 1:
            return False

        # Prevent cycles
        visited = set()

        def walk(node_name):
            if node_name in visited:
                return False  # cycle detected
            visited.add(node_name)

            children = [a["name"] for a in agents if a.get("parent") == node_name]
            return all(walk(child) for child in children)

        root = roots[0]["name"]
        return walk(root)
    # -------------------------------------------------------------
    # CROSS-VALIDATION (reference checks)
    # -------------------------------------------------------------
    def cross_validate(self):
        """
        Check that referenced SSH profiles, ports, or connections exist.
        Light version — expand as needed.
        """
        cm_store = self.other("connection_manager")
        if not cm_store:
            return True

        cm = cm_store.get_data() or {}
        data = self.get_data()

        for dep_id, cfg in data.items():
            text = str(cfg)
            for conn_id in cm:
                # If deployment references a missing connection, fail
                if conn_id in text and conn_id not in cm:
                    print(f"[DEPLOYMENTS][XVAL] ❌ Deployment '{dep_id}' references missing connection '{conn_id}'")
                    return False

        return True

    # -------------------------------------------------------------
    # HIGH-LEVEL MUTATION API (Commander Edition)
    # -------------------------------------------------------------
    def update_dep(self, dep_id, patch: dict):
        """
        Atomic update helper:
            • Merge patch into deployments[dep_id]
            • Validate
            • Commit
        """
        data = self.get_data()

        # Create deployment entry if missing
        dep = data.setdefault(dep_id, {})

        # Merge patch (deep, if nested dicts)

        for k, v in patch.items():
            if isinstance(dep.get(k), dict) and isinstance(v, dict):
                dep[k].update(v)
            else:
                dep[k] = deepcopy(v)

        # Commit via VaultStore (→ vault_core.patch())
        return self.commit()

    def delete_dep(self, dep_id):
        """
        Controlled deletion through store API.
        """
        data = self.get_data()
        if dep_id in data:
            data.pop(dep_id)
            return self.commit()
        return False

