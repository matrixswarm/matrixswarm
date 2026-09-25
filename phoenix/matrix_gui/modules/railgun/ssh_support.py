# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Shared SSH Registry and hardened authentication support for Railgun.
import base64
from dataclasses import dataclass
import getpass
import hmac
import io
import os
from pathlib import Path
import posixpath
import secrets
import shlex
import socket
import stat
import string
import subprocess
import tempfile
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


def generate_strong_passphrase(length=48):
    """Generate a whitespace-free passphrase with guaranteed character classes."""
    try:
        size = int(length)
    except (TypeError, ValueError) as exc:
        raise ValueError("Passphrase length must be an integer") from exc
    if size < 16:
        raise ValueError("Generated passphrases must be at least 16 characters")

    groups = (
        string.ascii_lowercase,
        string.ascii_uppercase,
        string.digits,
        string.punctuation,
    )
    alphabet = "".join(groups)
    characters = [secrets.choice(group) for group in groups]
    characters.extend(secrets.choice(alphabet) for _ in range(size - len(groups)))

    # Fisher-Yates with the OS-backed secrets generator prevents a predictable
    # character-class prefix without falling back to the PRNG in random.
    for index in range(len(characters) - 1, 0, -1):
        swap_index = secrets.randbelow(index + 1)
        characters[index], characters[swap_index] = (
            characters[swap_index],
            characters[index],
        )
    return "".join(characters)


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


def validate_ssh_install_target(key_profile, login_profile):
    """Fail closed before using vaulted credentials for an editor's target."""
    for profile in (key_profile, login_profile):
        if not clean_secret(profile.get("host")) or not clean_secret(profile.get("username")):
            raise ValueError("Both SSH profiles must specify a host and username.")
        try:
            port = int(profile.get("port", 22))
        except (TypeError, ValueError) as exc:
            raise ValueError("SSH target port is invalid.") from exc
        if not 1 <= port <= 65535:
            raise ValueError("SSH target port is invalid.")

    for field in ("host", "port", "username"):
        left, right = key_profile.get(field, 22), login_profile.get(field, 22)
        if field == "port":
            left, right = int(left), int(right)
        else:
            left, right = str(left).strip(), str(right).strip()
            if field == "host":
                left, right = left.casefold(), right.casefold()
        if left != right:
            raise ValueError(
                f"Editor target and Vault login profile have different {field} values. "
                "Select a login profile for the same host, port and account."
            )

    try:
        target_pin = normalize_fingerprint(key_profile.get("trusted_host_fingerprint"))
        login_pin = normalize_fingerprint(login_profile.get("trusted_host_fingerprint"))
    except ValueError as exc:
        raise ValueError("Both the editor target and Vault login profile need a pinned host key.") from exc
    if not hmac.compare_digest(target_pin, login_pin):
        raise ValueError("Editor target and Vault login profile have different pinned host keys.")


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
            key = key_type.from_private_key(
                io.StringIO(key_text),
                password=password,
            )
            if password:
                try:
                    key_type.from_private_key(
                        io.StringIO(key_text),
                        password=None,
                    )
                except (paramiko.SSHException, ValueError):
                    pass
                else:
                    raise ValueError(
                        "A passphrase was supplied, but this private key is "
                        "not encrypted"
                    )
            return key
        except (paramiko.SSHException, ValueError) as exc:
            errors.append(f"{key_type.__name__}: {exc}")

    raise ValueError(
        "Unsupported or invalid private key (RSA, Ed25519, and ECDSA "
        "are supported): " + "; ".join(errors)
    )


def public_key_from_private_key(key_pem, passphrase=None, comment="phoenix"):
    """Derive an authorized_keys line; never trust a separately pasted public key."""
    key = load_private_key(key_pem, passphrase)
    safe_comment = "_".join(str(comment or "phoenix").strip().split()) or "phoenix"
    return f"{key.get_name()} {key.get_base64()} {safe_comment}"


def _authorized_key_identity(value):
    """Return the algorithm/payload pair, tolerating authorized_keys options."""
    lexer = shlex.shlex(str(value or "").strip(), posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        # The key type is first, or second after an options field. Do not
        # mistake key-looking text inside a quoted command or comment for it.
        for _ in range(2):
            field = lexer.get_token()
            if field and field.startswith(("ssh-", "ecdsa-", "sk-")):
                payload = lexer.get_token()
                if not payload:
                    return None
                base64.b64decode(payload.encode("ascii"), validate=True)
                return field, payload
    except (ValueError, UnicodeEncodeError):
        return None
    return None


@dataclass(frozen=True)
class AuthorizedKeyInstallResult:
    installed: bool
    remote_path: str


def install_authorized_key(client, public_key):
    """Idempotently install one public key through an authenticated SSH client."""
    fields = str(public_key or "").strip().split()
    identity = _authorized_key_identity(public_key)
    if len(fields) < 2 or identity is None or tuple(fields[:2]) != identity:
        raise ValueError("Public key is not in authorized_keys format")
    canonical = " ".join(fields)

    sftp = client.open_sftp()
    try:
        home = posixpath.normpath(str(sftp.normalize(".")))
        if not home.startswith("/") or home == "/":
            raise RuntimeError("SSH account home directory is unsafe")
        ssh_dir = posixpath.join(home, ".ssh")
        authorized_keys = posixpath.join(ssh_dir, "authorized_keys")

        try:
            ssh_attrs = sftp.lstat(ssh_dir)
        except OSError as exc:
            if getattr(exc, "errno", None) != 2:
                raise
            sftp.mkdir(ssh_dir, mode=0o700)
        else:
            if stat.S_ISLNK(ssh_attrs.st_mode) or not stat.S_ISDIR(ssh_attrs.st_mode):
                raise RuntimeError("Remote .ssh path is not a real directory")
        sftp.chmod(ssh_dir, 0o700)

        existing = b""
        try:
            key_attrs = sftp.lstat(authorized_keys)
        except OSError as exc:
            if getattr(exc, "errno", None) != 2:
                raise
        else:
            if stat.S_ISLNK(key_attrs.st_mode) or not stat.S_ISREG(key_attrs.st_mode):
                raise RuntimeError("Remote authorized_keys is not a regular file")
            if key_attrs.st_size > 1024 * 1024:
                raise RuntimeError("Remote authorized_keys exceeds the 1 MiB safety limit")
            with sftp.open(authorized_keys, "rb") as handle:
                existing = handle.read(1024 * 1024 + 1)

        for raw_line in existing.decode("utf-8", "strict").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if _authorized_key_identity(line) == identity:
                sftp.chmod(authorized_keys, 0o600)
                return AuthorizedKeyInstallResult(False, authorized_keys)

        with sftp.open(authorized_keys, "ab") as handle:
            if existing and not existing.endswith(b"\n"):
                handle.write(b"\n")
            handle.write((canonical + "\n").encode("utf-8"))
            handle.flush()
        sftp.chmod(authorized_keys, 0o600)
        # A successful write alone is not proof that the intended key is there.
        with sftp.open(authorized_keys, "rb") as handle:
            stored = handle.read(1024 * 1024 + len(canonical.encode("utf-8")) + 2)
        if not any(
            line.strip() and not line.lstrip().startswith("#")
            and _authorized_key_identity(line) == identity
            for line in stored.decode("utf-8", "strict").splitlines()
        ):
            raise RuntimeError("Public key was not found in authorized_keys after writing.")
        return AuthorizedKeyInstallResult(True, authorized_keys)
    finally:
        sftp.close()


def _atomic_write(path: Path, content: str, mode: int, hardener=None):
    if os.path.lexists(path) and path.is_symlink():
        raise ValueError(f"Refusing to overwrite symbolic link: {path}")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        os.chmod(temporary, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = None
            handle.write(content.rstrip("\r\n") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if hardener is not None:
            hardener(Path(temporary))
        os.replace(temporary, path)
        os.chmod(path, mode)
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _harden_private_key_file(path: Path):
    os.chmod(path, 0o600)
    if os.name != "nt":
        return
    result = subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{getpass.getuser()}:(F)",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise OSError("Windows could not restrict the private-key ACL")


def save_ssh_key_pair(private_path, private_key, public_key):
    """Atomically export a private key and its sibling .pub file."""
    target = Path(os.path.abspath(os.path.expanduser(str(private_path))))
    if not target.name or (target.exists() and target.is_dir()):
        raise ValueError("Private-key destination must be a file")
    private_text = clean_secret(private_key)
    public_text = clean_secret(public_key)
    if not private_text or not public_text:
        raise ValueError("Private and public key material are required")
    public_target = Path(str(target) + ".pub")

    _atomic_write(
        target,
        private_text,
        0o600,
        hardener=_harden_private_key_file,
    )
    _atomic_write(public_target, public_text, 0o644)
    return str(target), str(public_target)


def load_registry_ssh_profiles():
    """Return a detached snapshot of SSH records from Registry Explorer."""
    registry_store = VaultCoreSingleton.get().get_store("registry")
    namespace = registry_store.get_namespace("ssh")

    profiles = {}
    for serial, record in namespace.items():
        if isinstance(record, dict):
            profiles[str(serial)] = dict(record)
    return profiles


def format_ssh_profile_label(serial, profile):
    """Render enough pinned identity to distinguish look-alike SSH records."""
    profile = profile if isinstance(profile, dict) else {}
    serial_text = str(serial or profile.get("serial") or "unknown")
    label = clean_secret(profile.get("label")) or "SSH"
    host = clean_secret(profile.get("host")) or "?"
    username = clean_secret(profile.get("username")) or "?"
    try:
        port = int(profile.get("port", 22))
    except (TypeError, ValueError):
        port = profile.get("port") or "?"

    fingerprint = clean_secret(profile.get("trusted_host_fingerprint"))
    fingerprint_tail = fingerprint[-10:] if fingerprint else "missing"
    serial_tail = serial_text[-8:]
    return (
        f"{label} · {username}@{host}:{port} · "
        f"id:{serial_tail} · fp:…{fingerprint_tail}"
    )


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
