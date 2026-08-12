# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import uuid, time, threading

class VaultSyncChannel:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, conn):
        self.conn = conn
        self._last_sync = 0

    @classmethod
    def init(cls, conn):
        """Initialize once (called from SessionWindow.__init__)."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = VaultSyncChannel(conn)
        return cls._instance

    @classmethod
    def get(cls):
        if cls._instance is None:
            raise RuntimeError("VaultSyncChannel not initialized")
        return cls._instance
    def create(self, deployment_id, payload):
        self._send("create", deployment_id, payload)

    def read(self, deployment_id=None):
        self._send("read", deployment_id)
        # cockpit will respond with the data over same conn

    def update(self, deployment_id, payload):
        self._send("update", deployment_id, payload)

    def delete(self, deployment_id):
        self._send("delete", deployment_id)

    def _send(self, op, deployment_id=None, payload=None):
        try:
            msg = {
                "type": "vault_crud",
                "op": op,
                "deployment_id": deployment_id,
                "payload": payload,
                "ts": time.time(),
                "uuid": uuid.uuid4().hex
            }
            self.conn.send(msg)
        except (BrokenPipeError, OSError) as e:
            print(f"[VAULTSYNC][ERROR] send failed ({op}): {e}")
