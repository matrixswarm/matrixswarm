"""Stable retry identities; explicit new operations are saved before dispatch."""
import hashlib
import json
from copy import deepcopy
import uuid


def request_identity(vault, target, intent, *, new_operation=False):
    scope = {"host": str(target.get("host", "")).strip().lower(),
             "port": int(target.get("port", 22)),
             "host_pin": target.get("trusted_host_fingerprint", ""),
             "intent": intent}
    key = hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    overrides = deepcopy(vault.data.get("railgun_request_overrides", {}))
    if not isinstance(overrides, dict):
        raise ValueError("Invalid Railgun request ledger")
    if new_operation:
        request_id = uuid.uuid4().hex
        overrides[key] = request_id
        if not vault.patch("railgun_request_overrides", overrides):
            raise RuntimeError("Could not save the new operation identity; nothing dispatched")
        return request_id
    request_id = overrides.get(key, key)
    if not isinstance(request_id, str) or len(request_id) not in (32, 64) or any(c not in "0123456789abcdef" for c in request_id):
        raise ValueError("Invalid saved Railgun request identity")
    return request_id
