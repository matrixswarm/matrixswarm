# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
from .vault_store_base import VaultStore
from copy import deepcopy

class RegistryStore(VaultStore):
    def __init__(self, root_vault):
        super().__init__(root_vault, "registry")

    def validate_key(self, namespace, objects):
        return isinstance(objects, dict)

    def validate_store(self):
        data = self.get_data()
        if not isinstance(data, dict):
            return False
        for ns, objs in data.items():
            if not self.validate_key(ns, objs):
                print(f"[REGISTRY][VALIDATION] ❌ Invalid namespace '{ns}'")
                return False
        return True

    def get_namespace(self, key):
        # use LIVE store data
        data = self.get_data()   # LIVE reference to vault["registry"]
        return data.setdefault(key, {})

    def set_namespace(self, ns, obj_dict):
        # Must write into LIVE vault dict
        data = self.get_data()
        data[ns] = deepcopy(obj_dict)
        return self.commit()
