# registry_singleton.py
# Commander Edition – Global Registry Store (pipeless)

import threading

class RegistrySingleton:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.registry = {}       # Everything under vault["registry"]
        self.vault = None        # Pointer to actual vault data branch
        self.initialized = False

    @classmethod
    def get(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = RegistrySingleton()
            return cls._instance

    def bind_to_vault(self, vault_data: dict):
        """Bind this registry to the vault's registry branch."""
        self.vault = vault_data
        self.registry = self.vault.setdefault("registry", {})
        self.initialized = True

    def list_namespaces(self):
        return sorted(self.registry.keys())

    def get_namespace(self, ns):
        return self.registry.setdefault(ns, {})

    def get_value(self, ns, key, default=None):
        return self.registry.get(ns, {}).get(key, default)

    def set(self, ns, key, value):
        self.registry.setdefault(ns, {})[key] = value

    def delete(self, ns, key):
        if ns in self.registry and key in self.registry[ns]:
            del self.registry[ns][key]

    def save(self):
        """Return updated vault to the caller so Phoenix can save."""
        return self.vault
