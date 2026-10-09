"""Fail-closed policy model for Phoenix Terminal access authoring.

This module deliberately contains no Qt and starts no listener.  Phoenix uses
it to persist an operator-authored policy in the Vault; Phoenix Terminal may
later validate the same record before presenting a connection approval.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping


SECTION_KEY = "terminal_access"
SCHEMA_VERSION = 1
MIN_APPROVAL_LIFETIME_SECONDS = 60
MAX_APPROVAL_LIFETIME_SECONDS = 3600
DEFAULT_APPROVAL_LIFETIME_SECONDS = 900

# Only operations with a real, separately reviewed adapter belong here.  A
# forged record cannot invent authority because unknown names fail validation.
SUPPORTED_OPERATIONS = frozenset({"alerts.read", "swarms.list", "railgun.launch", "agents.list", "logs.read", "sessions.list", "sessions.open"})


class TerminalAccessPolicyError(ValueError):
    """The stored policy is malformed or attempts to widen authority."""


@dataclass(frozen=True)
class OperationGrant:
    enabled: bool
    deployment_ids: tuple[str, ...]


@dataclass(frozen=True)
class TerminalAccessPolicy:
    enabled: bool
    approval_lifetime_seconds: int
    permissions: Mapping[str, OperationGrant]

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "enabled": self.enabled,
            "approval_lifetime_seconds": self.approval_lifetime_seconds,
            "permissions": {
                operation: {
                    "enabled": grant.enabled,
                    "deployment_ids": list(grant.deployment_ids),
                }
                for operation, grant in sorted(self.permissions.items())
            },
        }


def deployment_ids(vault_data: Mapping[str, Any]) -> tuple[str, ...]:
    """Return exact prepared-deployment identifiers or reject the Vault."""
    if not isinstance(vault_data, Mapping):
        raise TerminalAccessPolicyError("Vault data must be an object")
    deployments = vault_data.get("deployments", {})
    if not isinstance(deployments, Mapping):
        raise TerminalAccessPolicyError("Vault deployments must be an object")
    result: list[str] = []
    for deployment_id, value in deployments.items():
        if not isinstance(deployment_id, str) or not deployment_id.strip():
            raise TerminalAccessPolicyError("Deployment IDs must be nonempty strings")
        if not isinstance(value, Mapping):
            raise TerminalAccessPolicyError(
                f"Deployment {deployment_id!r} must be an object"
            )
        result.append(deployment_id)
    return tuple(result)


def default_policy() -> TerminalAccessPolicy:
    return TerminalAccessPolicy(
        enabled=False,
        approval_lifetime_seconds=DEFAULT_APPROVAL_LIFETIME_SECONDS,
        permissions={
            operation: OperationGrant(enabled=False, deployment_ids=())
            for operation in SUPPORTED_OPERATIONS
        },
    )


def _exact_keys(value: Mapping[str, Any], allowed: set[str], context: str) -> None:
    extras = set(value).difference(allowed)
    if extras:
        names = ", ".join(sorted(map(str, extras)))
        raise TerminalAccessPolicyError(f"Unknown {context} field(s): {names}")


def validate_policy(
    record: Any,
    prepared_deployment_ids: Iterable[str],
) -> TerminalAccessPolicy:
    """Strictly validate a persisted policy against the prepared Vault.

    Missing policy data means access is off.  Malformed or stale policy data is
    rejected rather than partially honored.
    """
    prepared = tuple(prepared_deployment_ids)
    if len(prepared) != len(set(prepared)) or any(
        not isinstance(item, str) or not item.strip() for item in prepared
    ):
        raise TerminalAccessPolicyError("Prepared deployment IDs are invalid")
    prepared_set = set(prepared)

    if record is None or record == {}:
        return default_policy()
    if not isinstance(record, Mapping):
        raise TerminalAccessPolicyError("Terminal access policy must be an object")
    _exact_keys(
        record,
        {"schema_version", "enabled", "approval_lifetime_seconds", "permissions"},
        "policy",
    )
    if type(record.get("schema_version")) is not int or record.get("schema_version") != SCHEMA_VERSION:
        raise TerminalAccessPolicyError("Unsupported Terminal access policy version")
    enabled = record.get("enabled")
    if type(enabled) is not bool:
        raise TerminalAccessPolicyError("Policy enabled must be true or false")
    lifetime = record.get("approval_lifetime_seconds")
    if type(lifetime) is not int or not (
        MIN_APPROVAL_LIFETIME_SECONDS
        <= lifetime
        <= MAX_APPROVAL_LIFETIME_SECONDS
    ):
        raise TerminalAccessPolicyError(
            "Approval lifetime must be an integer from 60 to 3600 seconds"
        )
    raw_permissions = record.get("permissions")
    if not isinstance(raw_permissions, Mapping):
        raise TerminalAccessPolicyError("Policy permissions must be an object")
    unknown_operations = set(raw_permissions).difference(SUPPORTED_OPERATIONS)
    if unknown_operations:
        names = ", ".join(sorted(map(str, unknown_operations)))
        raise TerminalAccessPolicyError(f"Unsupported operation(s): {names}")

    permissions: dict[str, OperationGrant] = {}
    for operation in sorted(SUPPORTED_OPERATIONS):
        raw_grant = raw_permissions.get(
            operation, {"enabled": False, "deployment_ids": []}
        )
        if not isinstance(raw_grant, Mapping):
            raise TerminalAccessPolicyError(f"Grant for {operation} must be an object")
        _exact_keys(raw_grant, {"enabled", "deployment_ids"}, f"{operation} grant")
        grant_enabled = raw_grant.get("enabled")
        if type(grant_enabled) is not bool:
            raise TerminalAccessPolicyError(
                f"Grant enabled flag for {operation} must be true or false"
            )
        raw_ids = raw_grant.get("deployment_ids")
        if not isinstance(raw_ids, list):
            raise TerminalAccessPolicyError(
                f"Deployment scope for {operation} must be a list"
            )
        if any(not isinstance(item, str) or not item.strip() for item in raw_ids):
            raise TerminalAccessPolicyError(
                f"Deployment scope for {operation} contains an invalid ID"
            )
        if len(raw_ids) != len(set(raw_ids)):
            raise TerminalAccessPolicyError(
                f"Deployment scope for {operation} contains duplicate IDs"
            )
        foreign = set(raw_ids).difference(prepared_set)
        if foreign:
            names = ", ".join(sorted(foreign))
            raise TerminalAccessPolicyError(
                f"Deployment scope for {operation} is outside this Vault: {names}"
            )
        permissions[operation] = OperationGrant(
            enabled=grant_enabled,
            deployment_ids=tuple(raw_ids),
        )

    return TerminalAccessPolicy(
        enabled=enabled,
        approval_lifetime_seconds=lifetime,
        permissions=permissions,
    )


def policy_from_vault(vault_data: Mapping[str, Any]) -> TerminalAccessPolicy:
    return validate_policy(
        vault_data.get(SECTION_KEY),
        deployment_ids(vault_data),
    )


def allows(
    policy: TerminalAccessPolicy,
    operation: str,
    deployment_id: str,
) -> bool:
    """Answer one exact authorization question; never infer aliases."""
    if policy.enabled is not True or operation not in SUPPORTED_OPERATIONS:
        return False
    grant = policy.permissions.get(operation)
    return bool(
        grant is not None
        and grant.enabled is True
        and deployment_id in grant.deployment_ids
    )


def authorize_vault_operation(
    vault_data: Mapping[str, Any],
    operation: str,
    deployment_id: str,
) -> bool:
    """Validate every time and fail closed on malformed or forged policy."""
    try:
        policy = policy_from_vault(vault_data)
    except (TerminalAccessPolicyError, TypeError, ValueError):
        return False
    return allows(policy, operation, deployment_id)


def vault_revision(vault_data: Mapping[str, Any]) -> str:
    """Bind approval to the exact decrypted Vault snapshot without exposing it."""
    try:
        encoded = json.dumps(
            deepcopy(vault_data),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TerminalAccessPolicyError("Vault cannot be revision-bound") from exc
    return hashlib.sha256(encoded).hexdigest()
