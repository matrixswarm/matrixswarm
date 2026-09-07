"""Pinned-host SSH transport for Harvester's fixed matrixd read command."""

from __future__ import annotations

import base64
import hmac
import io
from hashlib import sha256
from typing import Any

import paramiko


_MATRIXD_LIST_EXEC = (
    "/matrix/.venv/bin/python3 /matrix/scripts/matrixd list --json"
)
MATRIXD_LIST_COMMAND = (
    'if [ "$(id -u)" -eq 0 ]; then '
    f"exec {_MATRIXD_LIST_EXEC}; "
    "elif command -v sudo >/dev/null 2>&1; then "
    f"exec /usr/bin/sudo -n {_MATRIXD_LIST_EXEC}; "
    "else exit 77; fi"
)


def connect_pinned(profile: dict[str, Any], timeout: int):
    host = _required(profile, "host")
    username = _required(profile, "username")
    fingerprint = _normalize_fingerprint(profile.get("trusted_host_fingerprint"))
    port = profile.get("port", 22)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
        raise ValueError("SSH port is invalid")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(_PinnedPolicy(fingerprint))
    args = {
        "hostname": host,
        "port": port,
        "username": username,
        "look_for_keys": False,
        "allow_agent": False,
        "timeout": timeout,
        "auth_timeout": timeout,
        "banner_timeout": timeout,
    }
    auth_type = str(profile.get("auth_type", "private_key")).strip().lower()
    if auth_type == "password":
        args["password"] = _required(profile, "password")
    elif auth_type == "private_key":
        args["pkey"] = _load_private_key(
            _required(profile, "private_key"),
            profile.get("private_key_passphrase"),
        )
    elif auth_type == "agent":
        args["allow_agent"] = True
    else:
        raise ValueError("SSH auth type is unsupported")
    try:
        client.connect(**args)
        transport = client.get_transport()
        if transport is None or not transport.is_active():
            raise paramiko.SSHException("SSH transport did not become active")
        actual = _fingerprint(transport.get_remote_server_key())
        if not hmac.compare_digest(fingerprint, _normalize_fingerprint(actual)):
            raise paramiko.SSHException("SSH host key changed during connection")
        return client
    except Exception:
        client.close()
        raise


def run_matrixd_list(
    profile: dict[str, Any], timeout: int, maximum_bytes: int = 1_048_576
) -> str:
    client = connect_pinned(profile, timeout)
    try:
        _stdin, stdout, stderr = client.exec_command(
            MATRIXD_LIST_COMMAND, timeout=timeout
        )
        output = stdout.read(maximum_bytes + 1)
        error = stderr.read(4_097)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            raise RuntimeError(
                f"remote matrixd list failed with status {exit_code}"
            )
        if error.strip():
            raise RuntimeError("remote matrixd list wrote to stderr")
        if len(output) > maximum_bytes:
            raise RuntimeError("remote matrixd list output exceeded limit")
        return output.decode("utf-8", errors="strict")
    finally:
        client.close()


class _PinnedPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected: str):
        self.expected = expected

    def missing_host_key(self, client, hostname, key):
        actual = _normalize_fingerprint(_fingerprint(key))
        if not hmac.compare_digest(self.expected, actual):
            raise paramiko.SSHException(
                f"SSH host-key fingerprint mismatch for {hostname}"
            )


def _load_private_key(pem: str, passphrase: Any = None):
    cleaned_passphrase = _clean_secret(passphrase)
    errors = []
    for key_type in (
        paramiko.RSAKey,
        paramiko.Ed25519Key,
        paramiko.ECDSAKey,
    ):
        try:
            return key_type.from_private_key(
                io.StringIO(pem),
                password=cleaned_passphrase,
            )
        except (paramiko.SSHException, ValueError) as exc:
            errors.append(type(exc).__name__)
    raise ValueError(
        "SSH private key is invalid or unsupported: " + ",".join(errors)
    )


def _fingerprint(key) -> str:
    digest = sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii")


def _normalize_fingerprint(value: Any) -> str:
    cleaned = str(value or "").strip()
    if not cleaned.startswith("SHA256:") or len(cleaned) < 16:
        raise ValueError("trusted SSH SHA256 fingerprint is required")
    return cleaned.rstrip("=")


def _required(profile: dict[str, Any], key: str) -> str:
    value = _clean_secret(profile.get(key))
    if value is None or any(
        character in value for character in ("\x00", "\r", "\n")
    ):
        raise ValueError(f"SSH profile field {key} is invalid")
    return value


def _clean_secret(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() == "none":
        return None
    return cleaned
