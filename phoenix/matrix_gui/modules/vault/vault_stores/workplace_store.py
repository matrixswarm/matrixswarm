# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
from .vault_store_base import VaultStore
from copy import deepcopy

class WorkspaceStore(VaultStore):
    """
    Commander Edition – Manages workspaces section in the vault.
    Provides CRUD for workspace entries used by the Swarm Workspace editor.
    """

    def __init__(self, root_vault):
        super().__init__(root_vault, "workspaces")

    # -------------------------------------------------------------
    # VALIDATION
    # -------------------------------------------------------------
    def validate_key(self, uid, cfg):
        return (
            isinstance(uid, str)
            and isinstance(cfg, dict)
            and "label" in cfg
            and "data" in cfg
        )

    def validate_store(self):
        data = self.root.data.setdefault(self.section_key, {})
        if not isinstance(data, dict):
            return False

        for uid, cfg in data.items():
            if not self.validate_key(uid, cfg):
                print(f"[WORKSPACES][VALIDATION] ❌ Invalid workspace '{uid}'")
                return False
        return True

    # -------------------------------------------------------------
    # CRUD — *** LIVE DICT ONLY ***
    # -------------------------------------------------------------
    def get_workspace(self, uuid, default=None):
        """Return deep copy of a single workspace entry."""
        data = self.get_data()
        return deepcopy(data.get(uuid, default if default is not None else {}))

    def update_workspace(self, uuid, patch):
        """Stage a patch and restore the section if its commit is rejected."""
        data = deepcopy(self.get_data())
        ws = data.setdefault(uuid, {})

        for k, v in patch.items():
            if isinstance(ws.get(k), dict) and isinstance(v, dict):
                ws[k].update(deepcopy(v))
            else:
                ws[k] = deepcopy(v)

        return self._commit_workspaces(data)

    def delete_workspace(self, uuid):
        data = deepcopy(self.get_data())
        if uuid in data:
            del data[uuid]
            return self._commit_workspaces(data)
        return False

    def list_workspaces(self):
        data = self.get_data()
        return [(uid, cfg.get("label", "(unnamed)")) for uid, cfg in data.items()]

    def _commit_workspaces(self, candidate):
        previous = deepcopy(self.get_data())
        live = self.get_data()
        live.clear()
        live.update(deepcopy(candidate))
        accepted = False
        try:
            accepted = self.commit()
            return accepted
        finally:
            if not accepted:
                live = self.get_data()
                live.clear()
                live.update(previous)
            self._buffer = self.get_data()
