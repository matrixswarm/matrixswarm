# Commander Edition – Unified, Protected, Single-Authority Vault System
import json
import threading
from pathlib import Path
from copy import deepcopy
from matrix_gui.core.event_bus import EventBus
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.vault.vault_stores.phoenix_vault_core import PhoenixVaultCore as StoreCore

class VaultCoreSingleton:
    _instance = None
    _lock = threading.RLock()

    @classmethod
    def initialize(cls, vault_data, password, vault_path):
        cls._instance = cls(vault_data, password, vault_path)
        print("[VAULT-CORE] Initialized central vault authority.")
        EventBus.emit("vault.core.ready")
        return cls._instance

    @classmethod
    def get(cls):
        if not cls._instance:
            raise RuntimeError("Vault not initialized.")
        return cls._instance

    # -----------------------------
    def __init__(self, vault_data, password, vault_path):

        try:
            self.password = password
            self.vault_path = Path(vault_path)
            self.data = deepcopy(vault_data)
            self.last_good = deepcopy(self.data)

            # DOMAIN STORE CORE
            self.store_core = StoreCore(self)

            self._listeners = set()

        except Exception as e:
            print(f"{str(e)}")

    # -----------------------------
    def get_store(self, name):
        return self.store_core.get_store(name)

    def read(self, safe=True):
        return deepcopy(self.data) if safe else self.data

    def get_section(self, key):
        """
        Always return the live vault section.
        Any edits to the returned dict are edits to the vault itself:** the REAL DEAL**.
        """
        return self.data.setdefault(key, {})

    def snapshot(self, key):
        """Return a deep copy of the vault section for read-only use."""
        from copy import deepcopy
        return deepcopy(self.data.get(key, {}))

    def listen(self, event_name: str):
        """Register a vault event to emit when data changes."""
        self._listeners.add(event_name)
        print(f"[VAULT-CORE] Event listener registered: {event_name}")

    def _emit_to_listeners(self):
        for evt in self._listeners:
            EventBus.emit(evt, vcs=self)

    # -----------------------------
    def patch(self, key, value):
        """Single choke point — all mutations flow through here."""
        with self._lock:

            if value is None:
                print(f"[VAULT][PROTECT] Refusing to remove section {key}.")
                return False

            self.data[key] = deepcopy(value)

            raw = json.dumps(self.data)
            if len(raw) < 200:
                print("[VAULT][PROTECT] Refusing to shrink vault unnaturally.")
                self.data = deepcopy(self.last_good)
                return False

            self.last_good = deepcopy(self.data)

            EventBus.emit("vault.update",
                          data=self.data,
                          password=self.password,
                          vault_path=str(self.vault_path))

            EventBus.emit("vault.core.update")

            return True

    def batch(self, *stores):
        """
        Execute multiple store commits atomically.
        If ANY fail validation, NO changes are persisted.
        """
        snapshots = {s.section_key: s.get_data() for s in stores}

        # Validate everything first
        for store in stores:
            if not store.validate_store():
                return False
            if not store.cross_validate():
                return False

        # Commit sequentially
        for store in stores:
            if not store.commit():
                # rollback
                for key, data in snapshots.items():
                    self.patch(key, data)
                return False

        return True
