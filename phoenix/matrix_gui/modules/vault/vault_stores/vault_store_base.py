# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals

from abc import ABC, abstractmethod
from copy import deepcopy

class VaultStore(ABC):
    """
    Base class for all domain-protected stores.
    Each store owns one vault section and enforces schema, domain rules,
    and commit validation.
    """

    def __init__(self, root_vault, section_key: str):
        self.root = root_vault
        self.section_key = section_key
        # Live reference – no deepcopy
        self._buffer = self.root.get_section(section_key)

    # -------------------------
    # SAFE READ
    # -------------------------
    def get_data(self):
        return self.root.get_section(self.section_key)

    def get_value(self, key, default=None):
        return deepcopy(self._buffer.get(key, default))

    # -------------------------
    # SAFE WRITE
    # -------------------------
    def set_value(self, key, value):
        self._buffer[key] = deepcopy(value)

    def delete(self, key):
        if key not in self._buffer:
            return False

        if not self.allow_delete(key):
            print(f"[STORE][{self.section_key}] ❌ Delete forbidden: {key}")
            return False

        if not self.allow_delete_relations(key):
            print(f"[STORE][{self.section_key}] ❌ Reverse-dependency prevents delete: {key}")
            return False

        del self._buffer[key]
        return True

    def allow_delete_relations(self, key):
        """
        Override to prevent delete if OTHER stores depend on this key.
        Example:
            - a connection is referenced by a deployment
            - a directive used by a deployment
        """
        return True

    def allow_delete(self, key) -> bool:
        """Override in subclass."""
        return True

    # -------------------------
    # DOMAIN VALIDATION
    # -------------------------
    def validate_key(self, key, value):
        """Override for per-item validation."""
        return True

    def validate_store(self):
        """Override for full-structure validation."""
        return True

    # -------------------------
    # COMMIT
    # -------------------------
    def commit(self):
        data_ref = self.get_data()  # live reference
        if not self.cross_validate():
            print(f"[STORE][{self.section_key}] ❌ Cross-store validation failed.")
            return False
        for k, v in data_ref.items():
            if not self.validate_key(k, v):
                print(f"[STORE][{self.section_key}] ❌ Key validation failed: {k}")
                return False
        if not self.validate_store():
            print(f"[STORE][{self.section_key}] ❌ Section validation failed.")
            return False
        success = self.root.patch(self.section_key, data_ref)
        if success:
            print(f"[STORE][{self.section_key}] ✅ COMMIT SUCCESS")
        else:
            print(f"[STORE][{self.section_key}] ❌ COMMIT FAILED")
        return success

    def cross_validate(self):
        """
        Override to validate relationships between this store's data
        and OTHER stores' data.
        """
        return True

    def other(self, name):
        """
        Access another store via the root vault.
        Example:
            conn_store = self.other("connection_manager")
        """
        return self.root.get_store(name)
