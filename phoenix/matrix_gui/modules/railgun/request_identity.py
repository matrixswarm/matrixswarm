"""Stable retry identities; explicit new operations are saved before dispatch."""
import hashlib
import json
from copy import deepcopy
import uuid

from matrix_gui.modules.railgun.remote_shell import (
    _ALLOWED_BOOT_FLAGS,
    default_linux_user,
    derive_runtime_capabilities,
)


class ControlIdentityError(RuntimeError):
    """A safe, non-secret reason to refuse a session control request."""


def request_scope_key(target, intent):
    scope = {"host": str(target.get("host", "")).strip().lower(),
             "port": int(target.get("port", 22)),
             "host_pin": target.get("trusted_host_fingerprint", ""),
             "intent": intent}
    return hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def request_identity(vault, target, intent, *, new_operation=False):
    key = request_scope_key(target, intent)
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


def session_control_identity(vault, deployment_id, action, flags, expected_scope_key,
                             *, new_operation=False):
    """Allocate a control receipt in the cockpit, against its live vault record."""
    if getattr(vault, "_closed", False):
        raise ControlIdentityError("VAULT_CLOSED")
    if action not in ("start", "restart") or type(new_operation) is not bool:
        raise ControlIdentityError("INVALID_REQUEST")
    if not isinstance(flags, list) or len(flags) > 8 or any(
        not isinstance(flag, str) or flag not in _ALLOWED_BOOT_FLAGS for flag in flags
    ) or len(set(flags)) != len(flags):
        raise ControlIdentityError("INVALID_REQUEST")
    if not isinstance(expected_scope_key, str) or len(expected_scope_key) != 64:
        raise ControlIdentityError("INVALID_REQUEST")
    record = vault.get_store("deployments").get_dep(deployment_id)
    if not isinstance(record, dict) or not record:
        raise ControlIdentityError("DEPLOYMENT_CHANGED")
    serial = record.get("ssh_serial")
    recorded_target = record.get("railgun_target_identity")
    registry = vault.read().get("registry", {})
    targets = registry.get("ssh", {}) if isinstance(registry, dict) else {}
    target = targets.get(serial) if isinstance(targets, dict) else None
    if not isinstance(target, dict) or not isinstance(recorded_target, dict):
        raise ControlIdentityError("TARGET_CHANGED")
    actual_target = {"host": str(target.get("host", "")).strip().lower(),
                     "port": int(target.get("port", 22)),
                     "pin": target.get("trusted_host_fingerprint", "")}
    if actual_target != recorded_target:
        raise ControlIdentityError("TARGET_CHANGED")
    stored_agents = record.get("agents", {})
    capabilities = (derive_runtime_capabilities(stored_agents) if stored_agents
                    else record.get("runtime_capabilities") or {})
    intent = {"action": action, "universe": record.get("universe") or record.get("label"),
              "linux_user": record.get("linux_user") or default_linux_user(record.get("label", "phoenix")),
              "flags": flags,
              "capabilities": capabilities, "bundle": record.get("encrypted_bundle")}
    if request_scope_key(target, intent) != expected_scope_key:
        raise ControlIdentityError("DEPLOYMENT_CHANGED")
    try:
        return request_identity(vault, target, intent, new_operation=new_operation)
    except RuntimeError as error:
        raise ControlIdentityError("SAVE_FAILED") from error
