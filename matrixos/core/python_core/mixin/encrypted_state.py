"""Reusable authenticated encrypted state for long-lived agents."""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Mapping

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class EncryptedStateError(RuntimeError):
    """Encrypted agent state could not be initialized, read, or written."""


class EncryptedStateMixin:
    """Opt-in encrypted JSON storage below an agent's static directory.

    Typical agent usage::

        class Agent(EncryptedStateMixin, BootAgent):
            def __init__(self):
                super().__init__()
                self.init_encrypted_state(namespace="cognitive")

        self.save_encrypted_state(
            "checkpoint", state, directory=f"runs/{run_id}"
        )
        state = self.load_encrypted_state(
            "checkpoint", directory=f"runs/{run_id}"
        )

    The namespace and optional directory are storage organization, key
    separation, and authenticated-encryption context. They are never accepted
    as unrestricted filesystem paths.
    """

    _state_name_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

    def init_encrypted_state(
        self,
        namespace: str = "agent_state",
        root: str | os.PathLike[str] | None = None,
        key_b64: str | None = None,
    ) -> None:
        """Initialize state after BootAgent initialization.

        By default Phoenix's ``symmetric_encryption`` constraint provides the
        key material and ``static_comm_path_resolved`` provides the base root.
        The optional root and key parameters are for migration/tests.
        """
        if not self._state_name_re.fullmatch(namespace):
            raise EncryptedStateError("invalid encrypted-state namespace")
        uid = getattr(self, "command_line_args", {}).get("universal_id")
        if not isinstance(uid, str) or not uid:
            raise EncryptedStateError("agent universal_id is required")
        material = key_b64 or self._phoenix_state_key()
        if not isinstance(material, str) or not material:
            raise EncryptedStateError(
                "Phoenix-provisioned symmetric_encryption key is required"
            )
        try:
            raw_key = base64.b64decode(material, validate=True)
        except Exception as exc:
            raise EncryptedStateError("agent state key is not valid base64") from exc
        if len(raw_key) < 16:
            raise EncryptedStateError("agent state key is too short")
        derived_key = HKDF(
            algorithm=SHA256(), length=32,
            salt=b"matrixswarm.encrypted-state.v1",
            info=f"{uid}:{namespace}".encode("utf-8"),
        ).derive(raw_key)
        if root is None:
            root = getattr(self, "path_resolution", {}).get(
                "static_comm_path_resolved"
            )
            if not isinstance(root, str) or not root:
                raise EncryptedStateError("static communication path is required")
        self._encrypted_state_uid = uid
        self._encrypted_state_namespace = namespace
        self._encrypted_state_root = Path(root).resolve() / namespace
        self._encrypted_state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self._encrypted_state_root, 0o700)
        except OSError:
            pass
        self._encrypted_state_aes = AESGCM(derived_key)
        self._encrypted_state_lock = threading.RLock()

    def _phoenix_state_key(self) -> str | None:
        tree_node = getattr(self, "tree_node", {})
        if not isinstance(tree_node, Mapping):
            return None
        config = tree_node.get("config", {})
        if not isinstance(config, Mapping):
            return None
        security = config.get("security", {})
        if not isinstance(security, Mapping):
            return None
        profile = security.get("symmetric_encryption", {})
        if not isinstance(profile, Mapping):
            return None
        key = profile.get("key")
        return key if isinstance(key, str) and key else None

    def load_encrypted_state(
        self,
        name: str,
        default: Any = None,
        *,
        directory: str | None = None,
    ) -> Any:
        """Load JSON state or a default from an optional nested directory."""
        path, relative_name = self._encrypted_state_path(name, directory)
        with self._encrypted_state_lock:
            if not path.exists():
                return default
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
                nonce = base64.b64decode(envelope["nonce"], validate=True)
                ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
                if envelope.get("v") != 1 or len(nonce) != 12:
                    raise ValueError("unsupported state envelope")
                plaintext = self._encrypted_state_aes.decrypt(
                    nonce, ciphertext, self._encrypted_state_aad(relative_name)
                )
                return json.loads(plaintext.decode("utf-8"))
            except Exception as exc:
                raise EncryptedStateError(f"cannot decrypt state '{name}'") from exc

    def save_encrypted_state(
        self,
        name: str,
        value: Any,
        *,
        directory: str | None = None,
    ) -> None:
        """Atomically encrypt JSON state in an optional nested directory."""
        path, relative_name = self._encrypted_state_path(
            name, directory, create_parent=True
        )
        try:
            plaintext = json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise EncryptedStateError("state value must be JSON-compatible") from exc
        nonce = os.urandom(12)
        ciphertext = self._encrypted_state_aes.encrypt(
            nonce, plaintext, self._encrypted_state_aad(relative_name)
        )
        envelope = json.dumps(
            {"v": 1, "nonce": base64.b64encode(nonce).decode("ascii"),
             "ciphertext": base64.b64encode(ciphertext).decode("ascii")},
            separators=(",", ":"),
        )
        with self._encrypted_state_lock:
            descriptor, temporary_name = tempfile.mkstemp(
                dir=self._encrypted_state_root, prefix=".state-", suffix=".tmp"
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
                    os.chmod(temporary_name, 0o600)
                    temporary.write(envelope)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_name, path)
                self._fsync_directory(path.parent)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)

    def delete_encrypted_state(
        self, name: str, *, directory: str | None = None
    ) -> bool:
        """Delete one state item. Returns False if it did not exist."""
        path, _relative_name = self._encrypted_state_path(name, directory)
        with self._encrypted_state_lock:
            try:
                path.unlink()
                self._fsync_directory(path.parent)
                return True
            except FileNotFoundError:
                return False

    def _encrypted_state_path(
        self,
        name: str,
        directory: str | None = None,
        *,
        create_parent: bool = False,
    ) -> tuple[Path, str]:
        if not hasattr(self, "_encrypted_state_root"):
            raise EncryptedStateError("call init_encrypted_state() first")
        if not isinstance(name, str) or not self._state_name_re.fullmatch(name):
            raise EncryptedStateError("invalid state name")
        parts = self._encrypted_state_directory_parts(directory)
        parent = self._encrypted_state_root.joinpath(*parts)
        if create_parent:
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                os.chmod(parent, 0o700)
            except OSError:
                pass
        relative_name = "/".join((*parts, name))
        return parent / f"{name}.json.aes", relative_name

    def _encrypted_state_directory_parts(
        self, directory: str | None
    ) -> tuple[str, ...]:
        if directory is None or directory == "":
            return ()
        if not isinstance(directory, str) or "\\" in directory:
            raise EncryptedStateError("invalid encrypted-state directory")
        parts = tuple(directory.split("/"))
        if not parts or any(
            not self._state_name_re.fullmatch(part) for part in parts
        ):
            raise EncryptedStateError("invalid encrypted-state directory")
        return parts

    def _encrypted_state_aad(self, relative_name: str) -> bytes:
        return (
            f"matrixswarm.encrypted-state.v1:"
            f"{self._encrypted_state_uid}:"
            f"{self._encrypted_state_namespace}:{relative_name}"
        ).encode("utf-8")

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        """Persist a rename/unlink on filesystems that support directory fsync."""
        descriptor = None
        try:
            descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            if descriptor is not None:
                os.close(descriptor)
