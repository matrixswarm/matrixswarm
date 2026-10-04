"""Drop Vault: authenticated shared clipboard/files, never a command executor."""
from __future__ import annotations

import os
import sys
for _path in (os.getenv("SITE_ROOT"), os.getenv("AGENT_PATH")):
    if _path:
        sys.path.insert(0, _path)

import hashlib
import re
import time
import traceback
from core.python_core.boot_agent import BootAgent
from core.python_core.mixin.encrypted_state import EncryptedStateMixin
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from drop_vault.store import DropStore, DropError


class Agent(EncryptedStateMixin, BootAgent):
    def __init__(self):
        super().__init__()
        self.name = "DropVault"
        if not self._phoenix_persistent_state_profile():
            raise RuntimeError("Drop Vault requires a dedicated Registry persistent_state assignment")
        self.init_encrypted_state(namespace="drop_vault")
        self.store = DropStore(self)
        self._rpc_role = self.tree_node.get("config", {}).get("rpc_router_role", "hive.rpc")
        self._cleanup_warning_at = 0
        self.log("[DROP_VAULT] Encrypted inbox ready; contents are never logged.")

    def cmd_request(self, content, packet, identity=None):
        if not (isinstance(content, dict)
                and content.get("target_universal_id") == self.command_line_args.get("universal_id")
                and isinstance(identity, IdentityObject) and identity.has_verified_identity()
                and identity.get_sender_uid() == self.get_matrix_universal_id()):
            self.log("[DROP_VAULT][REJECT] Unverified sender or wrong agent target.", level="WARNING")
            return
        for key in ("session_id", "token", "request_id"):
            if not isinstance(content.get(key), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", content[key]):
                self.log("[DROP_VAULT][REJECT] Invalid callback routing fields.", level="WARNING")
                return
        owner = hashlib.sha256((content["session_id"] + ":" + content["token"]).encode()).hexdigest()
        operation = content.get("operation")
        args = content.get("args")
        if operation in ("begin", "commit", "delete"):
            self.log(f"[DROP_VAULT] Accepted {operation} request; preparing session reply.")
        specs = {
            "list": ({"before"}, set()),
            "begin": ({"object_id", "kind", "title", "filename", "notes", "size", "sha256"},
                      {"object_id", "kind", "title", "filename", "notes", "size", "sha256"}),
            "chunk": ({"object_id", "offset", "data"}, {"object_id", "offset", "data"}),
            "commit": ({"object_id"}, {"object_id"}),
            "read": ({"object_id", "offset"}, {"object_id", "offset"}),
            "cancel": ({"object_id"}, {"object_id"}),
            "delete": ({"object_id"}, {"object_id"}),
        }
        try:
            if not isinstance(operation, str) or operation not in specs or not isinstance(args, dict):
                raise DropError("Unsupported inbox operation")
            allowed, required = specs[operation]
            if set(args) - allowed or required - set(args):
                raise DropError("Unexpected or missing request parameters")
            if operation == "list":
                result = self.store.listing(**args)
            elif operation in ("read", "delete"):
                result = getattr(self.store, operation)(**args)
            else:
                result = getattr(self.store, operation)(owner=owner, **args)
            payload = dict(result, ok=True)
        except DropError as exc:
            payload = {"ok": False, "error": str(exc)}
        except Exception as exc:
            locations = "; ".join(f"{f.name}:{f.lineno}" for f in traceback.extract_tb(exc.__traceback__))
            self.log(f"[DROP_VAULT] Request failed ({type(exc).__name__}) at {locations}", level="ERROR")
            payload = {"ok": False, "error": "Storage operation failed; check agent diagnostics. No success is implied."}
        sent = self.crypto_reply(response_handler="drop_vault.result", payload=dict(
            payload, agent_uid=self.command_line_args["universal_id"], token=content["token"],
            request_id=content["request_id"], operation=operation),
            session_id=content["session_id"], token=content["token"], rpc_role=self._rpc_role, quiet=True)
        if not sent:
            self.log("[DROP_VAULT][ERROR] Session reply was not queued; check live RPC relay and callback signing.", level="ERROR")

    def worker(self, config=None, identity=None):
        self.store.maintain()
        self.store.collect_garbage()
        if self.store.cleanup_error and time.monotonic() - self._cleanup_warning_at >= 60:
            self._cleanup_warning_at = time.monotonic()
            self.log(f"[DROP_VAULT] Encrypted-object cleanup pending ({self.store.cleanup_error}); will retry.", level="WARNING")

    def worker_post(self):
        if hasattr(self, "store"):
            self.store.close()


if __name__ == "__main__":
    Agent().boot()
