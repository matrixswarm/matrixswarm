import threading, time, copy, uuid
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
        self._deferred_messages = []
        print(f"[VAULT-SINGLETON] Bound to deployment {dep_id}")

    def take_deferred_messages(self):
        messages, self._deferred_messages = self._deferred_messages, []
        return messages

    def request_railgun_identity(self, action, flags, expected_scope_key, *, new_operation):
        """Ask the cockpit vault to durably allocate this session's control ID."""
        request_id = uuid.uuid4().hex
        try:
            self._conn.send({"type": "railgun.request_identity", "dep_id": self._dep_id,
                             "request_id": request_id, "action": action, "flags": list(flags),
                             "expected_scope_key": expected_scope_key,
                             "new_operation": bool(new_operation)})
        except (OSError, EOFError) as error:
            raise RuntimeError("The cockpit connection is unavailable; nothing was sent.") from error
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if not self._conn.poll(min(0.1, max(0, deadline - time.monotonic()))):
                    continue
                response = self._conn.recv()
            except (OSError, EOFError) as error:
                raise RuntimeError("The cockpit connection was lost; nothing was sent.") from error
            if response.get("type") == "force_close":
                self._deferred_messages.append(response)
                raise RuntimeError("This session is closing; nothing was sent.")
            if (response.get("type") == "railgun.identity.response"
                    and response.get("request_id") == request_id
                    and response.get("dep_id") == self._dep_id):
                value = response.get("railgun_request_id")
                if response.get("ok") is True and isinstance(value, str) and len(value) in (32, 64):
                    return value
                code = response.get("code")
                reasons = {
                    "VAULT_CLOSED": "Unlock the Phoenix vault before controlling this session.",
                    "TARGET_CHANGED": "The deployment's recorded SSH target changed; reopen or redeploy it.",
                    "DEPLOYMENT_CHANGED": "The saved deployment changed; reopen this session before retrying.",
                    "SAVE_FAILED": "The vault could not save a new control request; nothing was sent.",
                    "INVALID_REQUEST": "The requested control operation was refused before dispatch.",
                    "CONTROL_UNAVAILABLE": "The cockpit could not validate this control request; nothing was sent.",
                }
                raise RuntimeError(reasons.get(code, "The cockpit refused the control request; nothing was sent."))
            self._deferred_messages.append(response)
        raise RuntimeError("The cockpit did not confirm the control request; nothing was sent.")

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
