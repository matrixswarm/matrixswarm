import threading, time, copy
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class VaultConnectionSingleton:
    _instance = None
    _lock = threading.RLock()

    @classmethod
    def get(cls, dep_id=None, conn=None):
        if cls._instance is None:
            cls._instance = cls(dep_id, conn)
        return cls._instance

    def __init__(self, dep_id, conn):
        if hasattr(self, "_initd"): return
        self._initd = True
        self._dep_id = dep_id
        self._conn = conn
        self._deployment = {}
        print(f"[VAULT-SINGLETON] Bound to deployment {dep_id}")

    def load(self, deployment: dict):
        with self._lock:
            self._deployment = deployment or {}

    # --- Write-through ---
    def update_field(self, key: str, value):
        """Update a field in the deployment, merging if it's a dict."""
        with self._lock:
            existing = self._deployment.get(key, {})
            if isinstance(existing, dict) and isinstance(value, dict):
                existing.update(value)
                merged = existing
            else:
                merged = value
            self._deployment[key] = merged
            try:
                payload = {
                    "type": "vault.update.requested",
                    "dep_id": self._dep_id,
                    "patch": {key: merged},
                }
                print(f"[VAULT-SINGLETON] ✉️ Sending merged update via pipe: {payload}")
                self._conn.send(payload)
            except (BrokenPipeError, OSError) as e:
                print(f"[VAULT-SINGLETON][WARN] ❌ Pipe send failed: {e}")

    # --- On-demand read ---
    def fetch_fresh(self, target="deployment", timeout=2.0):
        """Request a fresh deployment snapshot from cockpit."""
        try:

            req = {
                "type": "vault.query",
                "dep_id": self._dep_id,
                "target": target
            }
            print(f"[VAULT-SINGLETON] 📤 Querying cockpit for '{target}' data...")
            self._conn.send(req)
            start = time.time()
            while time.time() - start < timeout:
                if self._conn.poll(0.1):
                    msg = self._conn.recv()
                    if msg.get("type") == "vault.response" and msg.get("dep_id") == self._dep_id:
                        data = msg.get("data", {})
                        with self._lock:
                            self._deployment = data
                        return data
            print(f"[VAULT-SINGLETON][WARN] No response within {timeout}s")
            return self.read_deployment()
        except Exception as e:
            emit_gui_exception_log("VaultConnectionSingleton.fetch_fresh", e)
            return self.read_deployment()

    def read_deployment(self):
        with self._lock:
            return copy.deepcopy(self._deployment)

