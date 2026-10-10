"""Detached, serialized writes to the encrypted vault's access_control section.

Unlike VaultStore's legacy live buffers, this store never mutates root.data
before the writer acknowledges persistence. Public listings exclude key material
and credential verifiers. Only trusted authority code uses _snapshot().
"""

import base64
from datetime import datetime
import re
import threading

from matrix_gui.modules.access_control.models import (
    AccessControlError, MAX_CREDENTIALS, MAX_PERMISSIONS, Permission, Target, VaultWriteError,
)


SECTION_KEY = "access_control"
_HEX_256 = re.compile(r"[0-9a-f]{64}\Z")
MIN_LIFETIME_SECONDS = 60
MAX_LIFETIME_SECONDS = 3600
DEFAULT_LIFETIME_SECONDS = 900


def validate_policy(enabled, lifetime, permissions):
    if type(enabled) is not bool:
        raise ValueError("Access-control enabled must be a boolean")
    if type(lifetime) is not int or not MIN_LIFETIME_SECONDS <= lifetime <= MAX_LIFETIME_SECONDS:
        raise ValueError("Approval lifetime must be between 60 and 3600 seconds")
    if not isinstance(permissions, dict) or len(permissions) > MAX_PERMISSIONS:
        raise ValueError("Invalid access-control policy permissions")
    for action, rule in permissions.items():
        Permission(action)
        if not isinstance(rule, dict) or set(rule) != {"enabled", "deployment_ids"}:
            raise ValueError("Invalid action policy")
        if type(rule["enabled"]) is not bool:
            raise ValueError("Action enabled must be a boolean")
        identifiers = rule["deployment_ids"]
        if not isinstance(identifiers, list) or len(identifiers) > MAX_PERMISSIONS:
            raise ValueError("Invalid deployment allowlist")
        for identifier in identifiers:
            if identifier is None:
                raise ValueError("Invalid deployment identifier")
            Target(deployment_id=identifier)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Duplicate deployment identifiers")


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Invalid access-control timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Access-control timestamps must include a timezone")


def validate_section(section):
    """Reject malformed records rather than supplying permissive defaults."""
    if not isinstance(section, dict):
        raise ValueError("Invalid access_control section")
    if not section:
        return
    if set(section) != {
        "schema_version", "enabled", "approval_lifetime_seconds",
        "permissions", "issuer", "credentials",
    }:
        raise ValueError("Invalid access_control section fields")
    if type(section["schema_version"]) is not int or section["schema_version"] != 1:
        raise ValueError("Unsupported access_control schema version")
    validate_policy(section["enabled"], section["approval_lifetime_seconds"], section["permissions"])
    issuer = section["issuer"]
    if not isinstance(issuer, dict) or set(issuer) != {
        "key_id", "algorithm", "private_key_b64", "public_key_b64",
    }:
        raise ValueError("Invalid access-control issuer")
    if not isinstance(issuer["key_id"], str) or not _HEX_256.fullmatch(issuer["key_id"]):
        raise ValueError("Invalid issuer key identifier")
    if issuer["algorithm"] != "Ed25519":
        raise ValueError("Unsupported issuer algorithm")
    for name in ("private_key_b64", "public_key_b64"):
        value = issuer[name]
        if not isinstance(value, str) or len(value) != 44:
            raise ValueError("Invalid issuer key encoding")
        if len(base64.b64decode(value, validate=True)) != 32:
            raise ValueError("Invalid issuer key length")
    records = section["credentials"]
    if not isinstance(records, dict) or len(records) > MAX_CREDENTIALS:
        raise ValueError("Invalid credential collection")
    for credential_id, record in records.items():
        if not isinstance(credential_id, str) or not re.fullmatch(r"[0-9a-f]{32}", credential_id):
            raise ValueError("Invalid credential identifier")
        if not isinstance(record, dict) or set(record) != {
            "label", "created_at", "revoked_at", "generation", "secret_sha256",
        }:
            raise ValueError("Invalid credential record")
        label = record["label"]
        if not isinstance(label, str) or not label.strip() or len(label) > 120:
            raise ValueError("Invalid credential label")
        if any(ord(char) < 32 for char in label):
            raise ValueError("Invalid credential label")
        _timestamp(record["created_at"])
        if record["revoked_at"] is not None:
            _timestamp(record["revoked_at"])
        if type(record["generation"]) is not int or record["generation"] < 1:
            raise ValueError("Invalid credential generation")
        digest = record["secret_sha256"]
        if not isinstance(digest, str) or not _HEX_256.fullmatch(digest):
            raise ValueError("Invalid credential verifier")


class AccessControlStore:
    def __init__(self, root_vault):
        self.root = root_vault
        self._writer_thread = threading.get_ident()

    def _require_writer_thread(self):
        # Workspace save admission/completion belongs to the vault's GUI thread.
        # Keep new durable writes there too; transport threads only read/check.
        if threading.get_ident() != self._writer_thread:
            raise AccessControlError("Credential and policy writes must run on the vault owner thread")

    def _snapshot(self):
        with self.root._lock:
            if self.root._closed:
                raise AccessControlError("Vault is closed")
            section = self.root.snapshot(SECTION_KEY)
            validate_section(section)
            return section

    def list_credentials(self):
        """Detached operator metadata, including revoked records; no secrets."""
        return [
            {"credential_id": identifier, **{
                key: record[key] for key in (
                    "label", "created_at", "revoked_at", "generation",
                )
            }}
            for identifier, record in self._snapshot().get("credentials", {}).items()
        ]

    def _create(self, credential_id, record, issuer):
        self._require_writer_thread()
        def transform(section):
            validate_section(section)
            if not section:
                section = self._empty_section(issuer)
            records = section["credentials"]
            if len(records) >= MAX_CREDENTIALS or credential_id in records:
                raise AccessControlError("Credential capacity reached or identifier already exists")
            records[credential_id] = record
            validate_section(section)
            return section

        if not self.root.transform_section(SECTION_KEY, transform):
            raise VaultWriteError("Credential was not saved; vault is closed, busy, or saving failed")

    @staticmethod
    def _empty_section(issuer):
        return {
            "schema_version": 1, "enabled": False,
            "approval_lifetime_seconds": DEFAULT_LIFETIME_SECONDS,
            "permissions": {}, "issuer": issuer, "credentials": {},
        }

    def policy(self):
        section = self._snapshot()
        return {
            "schema_version": 1,
            "enabled": section.get("enabled", False),
            "approval_lifetime_seconds": section.get(
                "approval_lifetime_seconds", DEFAULT_LIFETIME_SECONDS,
            ),
            "permissions": section.get("permissions", {}),
        }

    def _set_policy(self, enabled, lifetime, permissions, issuer):
        self._require_writer_thread()
        validate_policy(enabled, lifetime, permissions)

        def transform(section):
            validate_section(section)
            if not section:
                section = self._empty_section(issuer)
            section.update(
                enabled=enabled, approval_lifetime_seconds=lifetime, permissions=permissions,
            )
            validate_section(section)
            return section

        if not self.root.transform_section(SECTION_KEY, transform):
            raise VaultWriteError("Policy was not saved; vault is closed, busy, or saving failed")

    def _revoke(self, credential_id, timestamp):
        self._require_writer_thread()
        def transform(section):
            validate_section(section)
            record = section.get("credentials", {}).get(credential_id)
            if record is None:
                raise AccessControlError("Unknown credential")
            if record["revoked_at"] is None:
                record["revoked_at"] = timestamp
            validate_section(section)
            return section

        if not self.root.transform_section(SECTION_KEY, transform):
            raise VaultWriteError(
                "Credential is disabled for this unlock, but revocation was not saved. "
                "Retry before reopening the vault."
            )
