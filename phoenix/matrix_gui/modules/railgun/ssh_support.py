# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Shared SSH Registry and hardened authentication support for Railgun.
import base64
import hmac
import io
import socket
from hashlib import sha256

import paramiko

from matrix_gui.modules.vault.services.vault_core_singleton import (
    VaultCoreSingleton,
)


def clean_secret(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() == "none":
        return None
    return cleaned


def sha256_fingerprint(key):
    digest = sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii")


def probe_ssh_host_fingerprint(host, port=22, timeout=8):
    """Read the SSH host key before authentication or credential exchange."""
    clean_host = clean_secret(host)
    if not clean_host:
        raise ValueError("SSH host is required")
    try:
        clean_port = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError("SSH port is invalid") from exc

    sock = transport = None
    try:
        sock = socket.create_connection(
            (clean_host, clean_port),
            timeout=timeout,
        )
        transport = paramiko.Transport(sock)
        transport.start_client(timeout=timeout)
        key = transport.get_remote_server_key()
        if key is None:
            raise paramiko.SSHException("SSH server did not present a host key")
        return sha256_fingerprint(key)
    finally:
        if transport is not None:
            transport.close()
        elif sock is not None:
            sock.close()


def normalize_fingerprint(value):
    cleaned = clean_secret(value)
    if not cleaned or not cleaned.startswith("SHA256:"):
        raise ValueError(
            "A trusted SHA256 host-key fingerprint is required"
        )
    return cleaned.rstrip("=")


class PinnedHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected_fingerprint):
        self.expected = normalize_fingerprint(expected_fingerprint)

    def missing_host_key(self, client, hostname, key):
        actual = normalize_fingerprint(sha256_fingerprint(key))
        if not hmac.compare_digest(self.expected, actual):
            raise paramiko.SSHException(
                "SSH host-key fingerprint mismatch for "
                f"{hostname}: expected {self.expected}, received {actual}"
            )


def load_private_key(key_pem, passphrase=None):
    key_text = clean_secret(key_pem)
    if not key_text:
        raise ValueError(
            "Private key is required for private-key auth"
        )

    password = clean_secret(passphrase)
    errors = []

    for key_type in (
        paramiko.RSAKey,
        paramiko.Ed25519Key,
        paramiko.ECDSAKey,
    ):
        try:
            return key_type.from_private_key(
                io.StringIO(key_text),
                password=password,
            )
        except (paramiko.SSHException, ValueError) as exc:
            errors.append(f"{key_type.__name__}: {exc}")

    raise ValueError(
        "Unsupported or invalid private key (RSA, Ed25519, and ECDSA "
        "are supported): " + "; ".join(errors)
    )


def load_registry_ssh_profiles():
    """Return a detached snapshot of SSH records from Registry Explorer."""
    registry_store = VaultCoreSingleton.get().get_store("registry")
    namespace = registry_store.get_namespace("ssh")

    profiles = {}
    for serial, record in namespace.items():
        if isinstance(record, dict):
            profiles[str(serial)] = dict(record)
    return profiles


def connect_ssh_profile(ssh_cfg, timeout=15):
    """Connect with explicit auth and a required pinned host fingerprint."""
    host = clean_secret(ssh_cfg.get("host"))
    username = clean_secret(ssh_cfg.get("username"))
    if not host or not username:
        raise ValueError("SSH profile is missing host or username")

    try:
        port = int(ssh_cfg.get("port", 22))
    except (TypeError, ValueError) as exc:
        raise ValueError("SSH profile has an invalid port") from exc

    auth_type = str(
        ssh_cfg.get("auth_type", "private_key")
    ).strip().lower()
    expected_fingerprint = ssh_cfg.get("trusted_host_fingerprint")
    normalized_expected = normalize_fingerprint(expected_fingerprint)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(
        PinnedHostKeyPolicy(normalized_expected)
    )

    connect_args = {
        "hostname": host,
        "port": port,
        "username": username,
        "look_for_keys": False,
        "allow_agent": False,
        "timeout": timeout,
        "auth_timeout": timeout,
        "banner_timeout": timeout,
    }

    if auth_type == "password":
        password = clean_secret(ssh_cfg.get("password"))
        if not password:
            raise ValueError("Password is required for password auth")
        connect_args["password"] = password
    elif auth_type == "private_key":
        connect_args["pkey"] = load_private_key(
            ssh_cfg.get("private_key"),
            ssh_cfg.get("private_key_passphrase"),
        )
    elif auth_type == "agent":
        connect_args["allow_agent"] = True
    else:
        raise ValueError(f"Unsupported SSH auth type: {auth_type}")

    try:
        client.connect(**connect_args)

        transport = client.get_transport()
        if transport is None or not transport.is_active():
            raise paramiko.SSHException(
                "SSH transport did not become active"
            )

        actual_fingerprint = sha256_fingerprint(
            transport.get_remote_server_key()
        )
        if not hmac.compare_digest(
            normalized_expected,
            normalize_fingerprint(actual_fingerprint),
        ):
            raise paramiko.SSHException(
                "SSH host-key fingerprint changed during connection"
            )

        return client, actual_fingerprint
    except Exception:
        client.close()
        raise