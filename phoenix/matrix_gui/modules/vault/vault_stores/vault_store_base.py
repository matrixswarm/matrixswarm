# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals

from abc import ABC, abstractmethod
from copy import deepcopy
from contextlib import nullcontext

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
    def _edit_lock(self):
        lock = getattr(self.root, "_lock", None)
        return lock if hasattr(lock, "__enter__") else nullcontext()

    def _write_busy(self):
        return (getattr(self.root, "_workspace_active", None) is not None
                or bool(getattr(self.root, "_workspace_queue", ())))

    def set_value(self, key, value):
        with self._edit_lock():
            if self._write_busy():
                raise RuntimeError("The vault is busy saving another change")
            self._buffer[key] = deepcopy(value)

    def delete(self, key):
        with self._edit_lock():
            if self._write_busy():
                raise RuntimeError("The vault is busy saving another change")
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
    def commit_candidate(self, candidate):
        """Validate and commit a detached section, restoring it on failure."""
        with self._edit_lock():
            if self._write_busy():
                return False
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
