"""Pinned-host SSH and rsync transport shared by RsyncBoy jobs."""

from __future__ import annotations

import hmac
import io
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass


def _clean_secret(value) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() == "none" else text


def _normalize_fingerprint(value) -> str:
    text = _clean_secret(value)
    if text.upper().startswith("SHA256:"):
        text = text[7:]
    return text.rstrip("=")


def _validate_private_key_passphrase(key_text: str, passphrase: str):
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError("Paramiko is required for private-key validation") from exc

    errors = []
    for key_type in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
        try:
            key_type.from_private_key(io.StringIO(key_text), password=passphrase or None)
            if passphrase:
                try:
                    key_type.from_private_key(io.StringIO(key_text), password=None)
                except (paramiko.SSHException, ValueError):
                    pass
                else:
                    raise ValueError(
                        "A passphrase was supplied, but this private key is not encrypted"
                    )
            return
        except (paramiko.SSHException, ValueError) as exc:
            errors.append(str(exc))
    raise ValueError("Invalid private key or passphrase: " + "; ".join(errors))


@dataclass(frozen=True)
class SSHProfile:
    host: str
    username: str
    port: int
    auth_type: str
    trusted_host_fingerprint: str
    password: str = ""
    private_key: str = ""
    private_key_passphrase: str = ""


def parse_ssh_profile(config: dict) -> SSHProfile:
    ssh = config.get("ssh", {}) or {}
    host = _clean_secret(ssh.get("ssh_host") or ssh.get("host"))
    username = _clean_secret(ssh.get("ssh_user") or ssh.get("username"))
    port = int(ssh.get("ssh_port") or ssh.get("port") or 22)
    auth_type = _clean_secret(ssh.get("auth_type") or "password").lower()
    fingerprint = _clean_secret(
        ssh.get("trusted_host_fingerprint") or ssh.get("host_fingerprint")
    )

    if not host or not username:
        raise ValueError("Missing SSH credentials: ssh.host and ssh.username required")
    if host.startswith("-") or any(char.isspace() for char in host):
        raise ValueError("config.ssh.host contains unsafe characters")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", username):
        raise ValueError("config.ssh.username contains unsafe characters")
    if not 1 <= port <= 65535:
        raise ValueError("config.ssh.port out of range")
    if auth_type not in {"password", "private_key", "agent"}:
        raise ValueError("config.ssh.auth_type must be password, private_key, or agent")
    if not fingerprint:
        raise ValueError("config.ssh.trusted_host_fingerprint is required")

    password = _clean_secret(ssh.get("password"))
    private_key = _clean_secret(ssh.get("private_key_pem") or ssh.get("private_key"))
    passphrase = _clean_secret(ssh.get("private_key_passphrase") or ssh.get("passphrase"))
    if auth_type == "password" and not password:
        raise ValueError("config.ssh.password is required for password authentication")
    if auth_type == "private_key" and not private_key:
        raise ValueError("config.ssh.private_key is required for private-key authentication")

    return SSHProfile(
        host=host,
        username=username,
        port=port,
        auth_type=auth_type,
        trusted_host_fingerprint=fingerprint,
        password=password,
        private_key=private_key,
        private_key_passphrase=passphrase,
    )


class SSHTransport:
    """Run non-interactive SSH/rsync commands against one pinned host."""

    def __init__(self, profile: SSHProfile):
        self.profile = profile
        self._tmp_dir = None
        self._known_hosts = None
        self._key_path = None

    def __enter__(self):
        self._require_binary("ssh")
        self._require_binary("ssh-keyscan")
        self._require_binary("ssh-keygen")
        if self.profile.auth_type in {"password", "private_key"} and (
            self.profile.auth_type == "password" or self.profile.private_key_passphrase
        ):
            self._require_binary("sshpass")

        self._tmp_dir = tempfile.mkdtemp(prefix="rsync_boy_ssh_")
        os.chmod(self._tmp_dir, 0o700)
        self._known_hosts = os.path.join(self._tmp_dir, "known_hosts")
        self._pin_host_key()

        if self.profile.auth_type == "private_key":
            _validate_private_key_passphrase(
                self.profile.private_key,
                self.profile.private_key_passphrase,
            )
            self._key_path = os.path.join(self._tmp_dir, "identity")
            with open(self._key_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(self.profile.private_key.rstrip() + "\n")
            os.chmod(self._key_path, 0o600)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._tmp_dir:
            shutil.rmtree(self._tmp_dir, ignore_errors=True)

    @staticmethod
    def _require_binary(name: str):
        if shutil.which(name) is None:
            raise RuntimeError(f"Required binary not found: {name}")

    def _pin_host_key(self):
        scan = subprocess.run(
            ["ssh-keyscan", "-p", str(self.profile.port), self.profile.host],
            capture_output=True,
            text=True,
            timeout=15,
        )
        lines = [line for line in scan.stdout.splitlines() if line and not line.startswith("#")]
        expected = _normalize_fingerprint(self.profile.trusted_host_fingerprint)
        accepted = []

        for index, line in enumerate(lines):
            candidate = os.path.join(self._tmp_dir, f"candidate_{index}")
            with open(candidate, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
            check = subprocess.run(
                ["ssh-keygen", "-lf", candidate, "-E", "sha256"],
                capture_output=True,
                text=True,
            )
            for token in check.stdout.split():
                if token.startswith("SHA256:") and hmac.compare_digest(
                    _normalize_fingerprint(token), expected
                ):
                    accepted.append(line)
                    break

        if not accepted:
            detail = (scan.stderr or "host did not present the trusted key").strip()
            raise RuntimeError(f"SSH host fingerprint verification failed: {detail}")

        with open(self._known_hosts, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(accepted) + "\n")
        os.chmod(self._known_hosts, 0o600)

    def _host_target(self) -> str:
        host = self.profile.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{self.profile.username}@{host}"

    def _ssh_argv(self) -> list[str]:
        argv = [
            "ssh",
            "-p", str(self.profile.port),
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self._known_hosts}",
            "-o", "ConnectTimeout=15",
        ]
        if self.profile.auth_type == "private_key":
            argv += ["-i", self._key_path, "-o", "IdentitiesOnly=yes"]
        argv += ["-o", f"BatchMode={'no' if self.profile.auth_type == 'password' else 'yes'}"]
        return argv

    def _auth_prefix_and_env(self):
        env = os.environ.copy()
        prefix = []
        if self.profile.auth_type == "password":
            env["SSHPASS"] = self.profile.password
            prefix = ["sshpass", "-e"]
        elif self.profile.auth_type == "private_key" and self.profile.private_key_passphrase:
            env["SSHPASS"] = self.profile.private_key_passphrase
            prefix = ["sshpass", "-P", "Enter passphrase for key", "-e"]
        return prefix, env

    def run(self, remote_command: str, *, check=True, capture_output=True):
        prefix, env = self._auth_prefix_and_env()
        return subprocess.run(
            [*prefix, *self._ssh_argv(), self._host_target(), remote_command],
            check=check,
            capture_output=capture_output,
            text=True,
            env=env,
        )

    def run_script(self, script: bytes, *, check=True, stdout=subprocess.PIPE):
        """Run a private shell script over SSH without placing it in process arguments."""
        prefix, env = self._auth_prefix_and_env()
        return subprocess.run(
            [*prefix, *self._ssh_argv(), self._host_target(), "bash -s"],
            input=script,
            stdout=stdout,
            stderr=subprocess.PIPE,
            check=check,
            env=env,
        )

    def path_exists(self, remote_path: str) -> bool:
        result = self.run(
            f"test -d {shlex.quote(remote_path)}",
            check=False,
        )
        return result.returncode == 0

    def rsync(self, source: str, remote_path: str, options=None):
        self._require_binary("rsync")
        prefix, env = self._auth_prefix_and_env()
        ssh_command = shlex.join(self._ssh_argv())
        target = f"{self._host_target()}:{shlex.quote(remote_path)}"
        return subprocess.run(
            [
                *prefix,
                "rsync",
                *(options or []),
                "-e", ssh_command,
                source,
                target,
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

    def rsync_from(self, remote_path: str, destination: str, options=None):
        """Pull one path from the pinned SSH host into a local destination."""
        self._require_binary("rsync")
        prefix, env = self._auth_prefix_and_env()
        ssh_command = shlex.join(self._ssh_argv())
        source = f"{self._host_target()}:{shlex.quote(remote_path)}"
        return subprocess.run(
            [
                *prefix,
                "rsync",
                *(options or []),
                "-e", ssh_command,
                "--",
                source,
                destination,
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
