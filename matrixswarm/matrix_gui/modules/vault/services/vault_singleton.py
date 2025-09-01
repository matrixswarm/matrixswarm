import threading
from matrix_gui.modules.vault.services.vault_obj import VaultObj
class VaultSingleton:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = VaultObj(*args, **kwargs)
            return cls._instance

    @classmethod
    def set(cls, obj):
        with cls._lock:
            cls._instance = obj

    @classmethod
    def clear(cls):
        with cls._lock:
            cls._instance = None