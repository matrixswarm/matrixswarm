import threading, time, copy, uuid
from functools import wraps
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log


class SerializedConnection:
    """Serialize pipe writes shared by the session GUI and worker threads."""
    def __init__(self, connection):
        self._connection = connection
        self._send_lock = threading.Lock()

    def send(self, value):
        with self._send_lock:
            return self._connection.send(value)

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _serialized_receive(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapped


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

    @_serialized_receive
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

    @_serialized_receive
    def update_embedded_source(self, agent_id, encoded_source, source_hash, expected_bundle_hash):
        """Save one boot-directive source through the cockpit's vault authority."""
        request_id = uuid.uuid4().hex
        try:
            self._conn.send({"type": "vault.embedded_source.update", "dep_id": self._dep_id,
                             "request_id": request_id, "agent_id": agent_id,
                             "source": encoded_source, "sha256": source_hash,
                             "expected_bundle_hash": expected_bundle_hash})
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if not self._conn.poll(min(0.1, max(0, deadline - time.monotonic()))):
                    continue
                response = self._conn.recv()
                if (response.get("type") == "vault.embedded_source.response"
                        and response.get("request_id") == request_id
                        and response.get("dep_id") == self._dep_id):
                    if response.get("ok") is True and response.get("sha256") == source_hash:
                        return True
                    reasons = {
                        "DEPLOYMENT_CHANGED": "The saved deployment changed; reopen the session and try again.",
                        "SOURCE_NOT_EMBEDDED": "This agent has no embedded source in the saved directive.",
                        "AGENT_NOT_UNIQUE": "The saved directive does not contain exactly one matching agent.",
                        "UNSUPPORTED_LANGUAGE": "This update currently supports Python agents only.",
                        "SAVED_REOPEN_REQUIRED": "The vault was saved, but Phoenix could not refresh its in-memory state. Reopen the vault before saving again.",
                        "SAVE_FAILED": "The vault could not save the directive. Fix the vault problem and retry.",
                    }
                    raise RuntimeError(reasons.get(response.get("code"), "The embedded source update was refused."))
                self._deferred_messages.append(response)
                if response.get("type") == "force_close":
                    raise RuntimeError("The session is closing; the save could not be confirmed.")
        except (BrokenPipeError, EOFError, OSError) as error:
            raise RuntimeError("The cockpit connection was lost; the save could not be confirmed.") from error
        raise RuntimeError("The cockpit did not confirm the save. Check the vault before retrying.")

    # --- Write-through ---
    def update_field(self, key: str, value):
        """Update the local copy only after the cockpit confirms the vault write."""
        with self._lock:
            existing = copy.deepcopy(self._deployment.get(key, {}))
            if isinstance(existing, dict) and isinstance(value, dict):
                existing.update(copy.deepcopy(value))
                merged = existing
            else:
                merged = copy.deepcopy(value)
            request_id = uuid.uuid4().hex
            try:
                payload = {
                    "type": "vault.update.requested",
                    "dep_id": self._dep_id,
                    "patch": {key: merged},
                    "request_id": request_id,
                }
                self._conn.send(payload)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if not self._conn.poll(min(0.1, max(0, deadline - time.monotonic()))):
                        continue
                    response = self._conn.recv()
                    if (response.get("type") == "vault.update.response"
                            and response.get("request_id") == request_id
                            and response.get("dep_id") == self._dep_id):
                        if not response.get("ok"):
                            raise RuntimeError("The vault rejected the save. Fix the vault problem and retry.")
                        self._deployment[key] = merged
                        return True
                    self._deferred_messages.append(response)
                    if response.get("type") == "force_close":
                        raise RuntimeError("The session is closing; the save could not be confirmed.")
            except (BrokenPipeError, EOFError, OSError) as e:
                raise RuntimeError("The cockpit connection was lost; the save could not be confirmed.") from e
            raise RuntimeError("The cockpit did not confirm the save. Check the vault before retrying.")

    # --- On-demand read ---
    @_serialized_receive
    def fetch_fresh(self, target="deployment", timeout=2.0):
        """Request a fresh deployment snapshot from cockpit."""
        request_id = uuid.uuid4().hex
        try:

            req = {
                "type": "vault.query",
                "dep_id": self._dep_id,
                "target": target,
                "request_id": request_id,
            }
            print(f"[VAULT-SINGLETON] 📤 Querying cockpit for '{target}' data...")
            self._conn.send(req)
            start = time.time()
            while time.time() - start < timeout:
                if self._conn.poll(0.1):
                    msg = self._conn.recv()
                    if (msg.get("type") == "vault.response" and msg.get("dep_id") == self._dep_id
                            and msg.get("target") == target and msg.get("request_id") == request_id):
                        data = msg.get("data", {})
                        if target == "deployment":
                            self._deployment = data
                        return data
                    self._deferred_messages.append(msg)
                    if msg.get("type") == "force_close":
                        return self.read_deployment() if target == "deployment" else {}
            print(f"[VAULT-SINGLETON][WARN] No response within {timeout}s")
            return self.read_deployment() if target == "deployment" else {}
        except Exception as e:
            emit_gui_exception_log("VaultConnectionSingleton.fetch_fresh", e)
            return self.read_deployment() if target == "deployment" else {}

    def read_deployment(self):
        with self._lock:
            return copy.deepcopy(self._deployment)
