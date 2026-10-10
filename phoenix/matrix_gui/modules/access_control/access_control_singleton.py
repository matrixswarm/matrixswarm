"""One parent-process authority; only trusted Phoenix code calls its admin API.

can() is a preview. commit() rechecks and performs a bounded local handoff under
the vault/revocation lock. A handoff already committed may finish after revoke.
This module does not authorize child processes by copying a boolean or token.
"""

import base64
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import inspect
import json
from multiprocessing import parent_process
import os
import re
import secrets
import time
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .models import (
    AccessControlError, AccessDenied, Credential, Grant, Permission, Target,
    TARGET_FIELDS, check_action, permissions_tuple,
)
from matrix_gui.modules.vault.vault_stores.access_control_store import (
    DEFAULT_LIFETIME_SECONDS, MAX_LIFETIME_SECONDS, MIN_LIFETIME_SECONDS, validate_policy,
)


_MAX_CONNECTIONS = 64
_MAX_GRANTS = 256
_MAX_REQUESTS = 2048
_MAX_TOKEN_CHARACTERS = 131072
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _b64(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


@dataclass
class _Connection:
    credential_id: str
    label: str
    credential_fingerprint: str
    deadline: float
    expires_unix: float
    requests: set = field(default_factory=set)


@dataclass(frozen=True)
class _LiveGrant:
    connection_id: str
    permissions: tuple
    policy_fingerprint: str
    deadline: float
    expires_unix: float
    token: str = field(repr=False)
    payload: bytes = field(repr=False)
    signature: bytes = field(repr=False)


class AccessControlSingleton:
    @classmethod
    def get(cls):
        """Resolve the object composed in the current vault, never a second copy."""
        from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
        if parent_process() is not None:
            raise AccessControlError("Access control is owned by the Phoenix parent process")
        vault = VaultCoreSingleton.get()
        instance = vault.access_control
        if instance._owner_pid != os.getpid():
            raise AccessControlError("Access control is owned by the Phoenix parent process")
        return instance

    def __init__(self, vault, *, ai_mode):
        if parent_process() is not None:
            raise AccessControlError("Child sessions must use the parent authority")
        if type(ai_mode) is not bool:
            raise ValueError("ai_mode must be a boolean")
        self._vault = vault
        self._store = vault.get_store("access_control")
        self._lock = vault._lock
        self._owner_pid = os.getpid()
        self._ai_mode = ai_mode
        self._epoch = uuid.uuid4().hex
        self._closed = False
        self._killed = False
        self._revoked_credentials = set()
        self._actions = {}
        self._connections = {}
        self._grants = {}

    @property
    def ai_mode(self):
        return self._ai_mode

    @property
    def accepting_connections(self):
        with self._lock:
            return self._ai_mode and not (self._killed or self._closed or self._vault._closed)

    def _require_open(self):
        if self._owner_pid != os.getpid() or self._closed or self._vault._closed:
            raise AccessDenied("Vault authority is closed or belongs to another process")

    def _require_ai(self):
        self._require_open()
        if not self._ai_mode or self._killed:
            raise AccessDenied("AI access is off for this unlock")

    def register_action(self, action, *, target_fields=()):
        """Trusted adapters declare exact required target fields; no wildcards."""
        check_action(action)
        if not isinstance(target_fields, (tuple, list)):
            raise ValueError("Use a tuple of target field names")
        if any(name not in TARGET_FIELDS for name in target_fields):
            raise ValueError("Unknown target field")
        if len(set(target_fields)) != len(target_fields):
            raise ValueError("Duplicate target fields")
        required = frozenset(target_fields)
        if required and "deployment_id" not in required:
            raise ValueError("Targeted actions must include deployment_id")
        with self._lock:
            self._require_open()
            if action in self._actions and self._actions[action] != required:
                raise AccessControlError("Action already registered with a different target schema")
            self._actions[action] = required

    def _validate_permission(self, permission):
        required = self._actions.get(permission.action)
        if required is None or set(permission.target.to_record()) != required:
            raise AccessDenied("Action is unregistered or its target is incomplete")

    @staticmethod
    def _new_issuer():
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes_raw()
        return {
            "algorithm": "Ed25519", "key_id": hashlib.sha256(public).hexdigest(),
            "private_key_b64": base64.b64encode(key.private_bytes_raw()).decode("ascii"),
            "public_key_b64": base64.b64encode(public).decode("ascii"),
        }

    @staticmethod
    def _issuer_key(section):
        issuer = section["issuer"]
        key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(issuer["private_key_b64"]))
        public = key.public_key().public_bytes_raw()
        if (
            not hmac.compare_digest(public, base64.b64decode(issuer["public_key_b64"]))
            or not hmac.compare_digest(hashlib.sha256(public).hexdigest(), issuer["key_id"])
        ):
            raise AccessDenied("Issuer key record is inconsistent")
        return key

    def policy(self):
        with self._lock:
            self._require_open()
            return self._store.policy()

    def set_policy(self, *, enabled, permissions, approval_lifetime_seconds=DEFAULT_LIFETIME_SECONDS):
        """Operator API. One shared permission table; invalidate old approvals."""
        permissions = deepcopy(permissions)
        validate_policy(enabled, approval_lifetime_seconds, permissions)
        with self._lock:
            self._require_open()
            self._store._require_writer_thread()
            section = self._store._snapshot()
            issuer = section.get("issuer") or self._new_issuer()
            self._connections.clear()
            self._grants.clear()
            self._store._set_policy(enabled, approval_lifetime_seconds, permissions, issuer)

    def create_credential(self, label):
        """Operator API. Random client secret returned once, verifier saved only."""
        if not isinstance(label, str) or not label.strip() or len(label) > 120:
            raise ValueError("Use a nonempty client label of at most 120 characters")
        if any(ord(char) < 32 for char in label):
            raise ValueError("Client label contains control characters")
        with self._lock:
            self._require_open()
            self._store._require_writer_thread()
            section = self._store._snapshot()
            issuer = section.get("issuer") or self._new_issuer()
            identifier = uuid.uuid4().hex
            secret = secrets.token_urlsafe(32)
            record = {
                "label": label.strip(), "created_at": _utc_now(), "revoked_at": None,
                "generation": 1, "secret_sha256": hashlib.sha256(secret.encode("ascii")).hexdigest(),
            }
            self._store._create(identifier, record, issuer)
            return Credential(identifier, record["label"], secret)

    def list_credentials(self):
        with self._lock:
            self._require_open()
            records = self._store.list_credentials()
            for record in records:
                record["disabled_this_unlock"] = record["credential_id"] in self._revoked_credentials
            return records

    def revoke_credential(self, credential_id):
        """Revoke live access first; a failed durable save never restores it."""
        with self._lock:
            self._require_open()
            self._store._require_writer_thread()
            if not isinstance(credential_id, str) or not re.fullmatch(r"[0-9a-f]{32}", credential_id):
                raise ValueError("Invalid credential identifier")
            if credential_id not in self._store._snapshot().get("credentials", {}):
                raise AccessControlError("Unknown credential")
            self._revoked_credentials.add(credential_id)
            for identifier, connection in tuple(self._connections.items()):
                if connection.credential_id == credential_id:
                    self.revoke_connection(identifier)
            self._store._revoke(credential_id, _utc_now())

    @staticmethod
    def _credential_fingerprint(section, credential_id):
        return _digest({
            "issuer": section.get("issuer"),
            "credential": section.get("credentials", {}).get(credential_id),
        })

    @staticmethod
    def _policy_fingerprint(section):
        return _digest({key: section[key] for key in (
            "enabled", "approval_lifetime_seconds", "permissions",
        )})

    @staticmethod
    def _policy_allows(section, permission):
        rule = section.get("permissions", {}).get(permission.action, {})
        if not section.get("enabled", False) or not rule.get("enabled", False):
            return False
        deployment_id = permission.target.deployment_id
        if deployment_id is None:
            # An explicitly registered global action has an empty deployment list.
            return rule["deployment_ids"] == []
        return deployment_id in rule["deployment_ids"]

    def _prune(self):
        now, wall = time.monotonic(), time.time()
        for identifier, connection in tuple(self._connections.items()):
            if now >= connection.deadline or wall >= connection.expires_unix:
                self.revoke_connection(identifier)
        for digest, grant in tuple(self._grants.items()):
            if now >= grant.deadline or wall >= grant.expires_unix:
                self._grants.pop(digest, None)

    def connect(self, credential_id, secret):
        """Authenticate a client; this creates no approved permissions."""
        if (
            not isinstance(credential_id, str) or not re.fullmatch(r"[0-9a-f]{32}", credential_id)
            or not isinstance(secret, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", secret)
        ):
            raise AccessDenied("Invalid client credential")
        return self._connect_digest(credential_id, hashlib.sha256(secret.encode("ascii")).hexdigest())

    def _enroll_transport(self, label, digest):
        """Owner-thread operator approval only, never exposed as an MCP method.

        The existing MCP transport proves possession of a random client secret.
        Persist its verifier after the operator approves; never retain the raw
        secret. A revoked identity cannot enroll itself again under a new label.
        """
        if (not isinstance(label, str) or not label.strip() or len(label) > 120
                or any(ord(c) < 32 for c in label)
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("Invalid transport credential")
        with self._lock:
            self._require_ai()
            self._store._require_writer_thread()
            section = self._store._snapshot()
            if not section.get("enabled"):
                raise AccessDenied("AI access policy is disabled")
            identifier = next((key for key, value in section.get("credentials", {}).items()
                               if hmac.compare_digest(value["secret_sha256"], digest)), None)
            if identifier is None:
                identifier = uuid.uuid4().hex
                self._store._create(identifier, {
                    "label": label.strip(), "created_at": _utc_now(), "revoked_at": None,
                    "generation": 1, "secret_sha256": digest,
                }, section.get("issuer") or self._new_issuer())
            return self._connect_digest(identifier, digest)

    def _connect_digest(self, credential_id, digest):
        """Trusted transport hook: caller already verified secret possession."""
        with self._lock:
            self._require_ai()
            self._prune()
            section = self._store._snapshot()
            record = section.get("credentials", {}).get(credential_id)
            if (
                not section.get("enabled", False) or record is None
                or record["revoked_at"] is not None or credential_id in self._revoked_credentials
                or not hmac.compare_digest(
                    digest, record["secret_sha256"],
                )
            ):
                raise AccessDenied("Invalid or disabled client credential")
            if len(self._connections) >= _MAX_CONNECTIONS:
                raise AccessDenied("Connection capacity reached")
            identifier = uuid.uuid4().hex
            self._connections[identifier] = _Connection(
                credential_id, record["label"], self._credential_fingerprint(section, credential_id),
                time.monotonic() + MAX_LIFETIME_SECONDS, time.time() + MAX_LIFETIME_SECONDS,
            )
            return identifier

    def _live_connection(self, connection_id, section):
        self._require_ai()
        self._prune()
        if not isinstance(connection_id, str) or not re.fullmatch(r"[0-9a-f]{32}", connection_id):
            raise AccessDenied("Invalid connection identifier")
        connection = self._connections.get(connection_id)
        if connection is None or not section.get("enabled", False):
            raise AccessDenied("Connection is unavailable")
        if (
            connection.credential_id in self._revoked_credentials
            or not hmac.compare_digest(
                connection.credential_fingerprint,
                self._credential_fingerprint(section, connection.credential_id),
            )
        ):
            self.revoke_connection(connection_id)
            raise AccessDenied("Client credential changed or was revoked")
        return connection

    def approve(self, connection_id, permissions, *, lifetime_seconds=None):
        """Trusted operator API. Sign a transient subset of the one saved policy."""
        permissions = permissions_tuple(permissions)
        if not permissions:
            raise ValueError("An approval must include at least one exact permission")
        with self._lock:
            self._require_ai()
            section = self._store._snapshot()
            connection = self._live_connection(connection_id, section)
            maximum = section["approval_lifetime_seconds"]
            lifetime = maximum if lifetime_seconds is None else lifetime_seconds
            if type(lifetime) is not int or not MIN_LIFETIME_SECONDS <= lifetime <= maximum:
                raise ValueError("Approval lifetime exceeds policy or is below 60 seconds")
            for permission in permissions:
                self._validate_permission(permission)
                if not self._policy_allows(section, permission):
                    raise AccessDenied("Approval exceeds the saved access-control policy")
            if len(self._grants) >= _MAX_GRANTS:
                raise AccessDenied("Approval capacity reached")
            deadline = min(time.monotonic() + lifetime, connection.deadline)
            expires_unix = min(time.time() + lifetime, connection.expires_unix)
            expires_at = datetime.fromtimestamp(expires_unix, timezone.utc).isoformat()
            payload = _canonical({
                "version": 1, "key_id": section["issuer"]["key_id"], "epoch": self._epoch,
                "approval_id": uuid.uuid4().hex, "connection_id": connection_id,
                "credential_id": connection.credential_id, "issued_at": _utc_now(),
                "expires_at": expires_at, "permissions": [item.to_record() for item in permissions],
            })
            signature = self._issuer_key(section).sign(payload)
            token = f"pac1.{_b64(payload)}.{_b64(signature)}"
            if len(token) > _MAX_TOKEN_CHARACTERS:
                raise ValueError("Approval contains too many target identifiers; approve fewer actions")
            self._grants[hashlib.sha256(token.encode("ascii")).hexdigest()] = _LiveGrant(
                connection_id, permissions, self._policy_fingerprint(section), deadline,
                expires_unix, token, payload, signature,
            )
            return Grant(connection_id, expires_at, token)

    def _authorize(self, permission, connection_id, token):
        self._require_open()
        if not self._ai_mode:
            if connection_id is None and token is None:
                return None  # Existing manual Phoenix behavior.
            raise AccessDenied("AI connections require an AI Mode unlock")
        self._require_ai()
        self._validate_permission(permission)
        if (
            not isinstance(connection_id, str) or not isinstance(token, str)
            or len(token) > _MAX_TOKEN_CHARACTERS
        ):
            raise AccessDenied("A current connection and approval are required")
        try:
            digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        except UnicodeEncodeError:
            raise AccessDenied("Invalid approval token") from None
        section = self._store._snapshot()
        connection = self._live_connection(connection_id, section)
        grant = self._grants.get(digest)
        if (
            grant is None or grant.connection_id != connection_id
            or not hmac.compare_digest(grant.token, token) or permission not in grant.permissions
            or not hmac.compare_digest(grant.policy_fingerprint, self._policy_fingerprint(section))
            or not self._policy_allows(section, permission)
        ):
            raise AccessDenied("Approval is expired, revoked, or does not cover this operation")
        public = base64.b64decode(section["issuer"]["public_key_b64"])
        if not hmac.compare_digest(hashlib.sha256(public).hexdigest(), section["issuer"]["key_id"]):
            raise AccessDenied("Issuer key record is inconsistent")
        Ed25519PublicKey.from_public_bytes(public).verify(grant.signature, grant.payload)
        if time.monotonic() >= grant.deadline or time.time() >= grant.expires_unix:
            self._grants.pop(digest, None)
            raise AccessDenied("Approval expired during authorization")
        return connection

    def can(self, action, *, target=None, connection_id=None, token=None):
        """UI preview only. Never use this boolean as a dispatch permit."""
        try:
            permission = Permission(action, Target() if target is None else target)
            with self._lock:
                self._authorize(permission, connection_id, token)
                return True
        except (AccessDenied, AccessControlError, ValueError, TypeError, InvalidSignature):
            return False

    def commit(self, action, handoff, *, target=None, connection_id=None, token=None, request_id=None):
        """Atomically check and invoke a trusted, bounded local queue handoff.

        No network I/O, user dialogs, await, or delayed authorization in handoff.
        Once entered, this action is committed; revoke cannot undo it. AI request
        IDs are consumed even if handoff raises, so a retry cannot dispatch twice.
        """
        if not callable(handoff) or inspect.iscoroutinefunction(handoff):
            raise ValueError("Use a synchronous trusted handoff")
        permission = Permission(action, Target() if target is None else target)
        with self._lock:
            connection = self._authorize(permission, connection_id, token)
            if connection is not None:
                if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
                    raise AccessDenied("A unique request ID is required")
                if request_id in connection.requests or len(connection.requests) >= _MAX_REQUESTS:
                    raise AccessDenied("Request already committed or connection request capacity reached")
                connection.requests.add(request_id)
            result = handoff()
            if inspect.isawaitable(result):
                if inspect.iscoroutine(result):
                    result.close()
                raise AccessControlError("Handoff returned delayed work; use a bounded synchronous queue handoff")
            return result

    def revoke_connection(self, connection_id):
        with self._lock:
            self._require_open()
            if not isinstance(connection_id, str) or not re.fullmatch(r"[0-9a-f]{32}", connection_id):
                raise ValueError("Invalid connection identifier")
            removed = self._connections.pop(connection_id, None) is not None
            for digest, grant in tuple(self._grants.items()):
                if grant.connection_id == connection_id:
                    self._grants.pop(digest, None)
            return removed

    def list_connections(self):
        """Operator-only live metadata; no bearer tokens or credential secrets."""
        with self._lock:
            self._require_open()
            self._prune()
            return [{
                "connection_id": identifier, "credential_id": connection.credential_id,
                "label": connection.label,
                "expires_at": datetime.fromtimestamp(connection.expires_unix, timezone.utc).isoformat(),
                "approvals": sum(grant.connection_id == identifier for grant in self._grants.values()),
                "committed_requests": len(connection.requests),
            } for identifier, connection in self._connections.items()]

    def kill_switch(self):
        """Latch AI access off until a fresh unlock; revoke all live connections."""
        with self._lock:
            self._require_open()
            self._killed = True
            count = len(self._connections)
            self._connections.clear()
            self._grants.clear()
            return count

    def close(self):
        with self._lock:
            self._closed = True
            self._killed = True
            self._connections.clear()
            self._grants.clear()
            self._actions.clear()
