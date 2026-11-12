# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
from .vault_store_base import VaultStore
from copy import deepcopy

class DirectiveStore(VaultStore):
    def __init__(self, root_vault):
        super().__init__(root_vault, "directives")

    def validate_key(self, uid, cfg):
        return (
            isinstance(cfg, dict)
            and "label" in cfg
            and "json" in cfg
        )

    def get_dir(self, directive_id, default=None):
        data = self.get_data() or {}
        return deepcopy(data.get(directive_id, default if default is not None else {}))

    def validate_store(self):
        data = self.get_data()
        if not isinstance(data, dict):
            return False
        for uid, cfg in data.items():
            if not self.validate_key(uid, cfg):
                print(f"[DIRECTIVES][VALIDATION] ❌ Invalid directive '{uid}'")
                return False
        return True

    def update_directive(self, uid, patch):
        data = deepcopy(self.get_data())
        d = data.setdefault(uid, {})
        for k, v in patch.items():
            if isinstance(d.get(k), dict) and isinstance(v, dict):
                d[k].update(v)
            else:
                d[k] = deepcopy(v)

        return self.commit_candidate(data)

    def delete_directive(self, uid):
        data = deepcopy(self.get_data())
        if uid in data:
            data.pop(uid)
            return self.commit_candidate(data)
        return False
