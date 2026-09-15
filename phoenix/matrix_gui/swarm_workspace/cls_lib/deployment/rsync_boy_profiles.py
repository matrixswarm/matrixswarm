"""Resolve RsyncBoy per-job SSH references into the encrypted directive."""

from copy import deepcopy
import re


_SAFE_PROFILE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RUNTIME_FIELDS = (
    "label",
    "host",
    "port",
    "username",
    "auth_type",
    "trusted_host_fingerprint",
    "password",
    "private_key",
    "private_key_passphrase",
)


class RsyncBoyProfileError(ValueError):
    """A referenced Registry SSH profile cannot be deployed safely."""


def _clean_secret(value):
    if value is None:
        return None
    value = str(value).strip()
    return None if not value or value.lower() == "none" else value


def _validate_runtime_profile(serial, record):
    if not isinstance(record, dict):
        raise RsyncBoyProfileError(
            f"RsyncBoy SSH profile '{serial}' is missing from Registry"
        )

    profile = {
        key: deepcopy(record.get(key))
        for key in _RUNTIME_FIELDS
        if key in record
    }
    profile["serial"] = serial

    host = _clean_secret(profile.get("host"))
    username = _clean_secret(profile.get("username"))
    fingerprint = _clean_secret(profile.get("trusted_host_fingerprint"))
    if not host or not username:
        raise RsyncBoyProfileError(
            f"RsyncBoy SSH profile '{serial}' is missing its host or username"
        )
    if not fingerprint or not fingerprint.startswith("SHA256:"):
        raise RsyncBoyProfileError(
            f"RsyncBoy SSH profile '{serial}' has no trusted SHA256 fingerprint"
        )
    try:
        port = int(profile.get("port", 22))
    except (TypeError, ValueError) as exc:
        raise RsyncBoyProfileError(
            f"RsyncBoy SSH profile '{serial}' has an invalid port"
        ) from exc
    if not 1 <= port <= 65535:
        raise RsyncBoyProfileError(
            f"RsyncBoy SSH profile '{serial}' has an invalid port"
        )

    auth_type = str(profile.get("auth_type", "private_key")).strip().lower()
    if auth_type == "password" and not _clean_secret(profile.get("password")):
        raise RsyncBoyProfileError(
            f"RsyncBoy SSH profile '{serial}' has no password"
        )
    if auth_type == "private_key" and not _clean_secret(profile.get("private_key")):
        raise RsyncBoyProfileError(
            f"RsyncBoy SSH profile '{serial}' has no private key"
        )
    if auth_type not in {"password", "private_key", "agent"}:
        raise RsyncBoyProfileError(
            f"RsyncBoy SSH profile '{serial}' has unsupported auth type '{auth_type}'"
        )

    profile.update(
        host=host,
        port=port,
        username=username,
        auth_type=auth_type,
        trusted_host_fingerprint=fingerprint,
    )
    return profile


def inject_rsync_boy_ssh_profiles(raw_nodes, ssh_namespace):
    """
    Add only explicitly referenced SSH Registry profiles to RsyncBoy configs.

    Job documents retain a non-secret Registry serial. The returned profile pool
    contains credentials and therefore belongs only in directive staging, which
    Phoenix encrypts before transport.
    """
    ssh_namespace = ssh_namespace if isinstance(ssh_namespace, dict) else {}
    injected = 0

    for node in raw_nodes.values():
        if str(node.get("name", "")).strip().lower() != "rsync_boy":
            continue
        config = node.setdefault("config", {})
        if not isinstance(config, dict):
            raise RsyncBoyProfileError("RsyncBoy config must be an object")

        # Never trust a previously staged credential pool from workspace data.
        config.pop("ssh_profiles", None)
        refs = []
        jobs = config.get("jobs", []) or []
        if not isinstance(jobs, list):
            raise RsyncBoyProfileError("RsyncBoy jobs must be a list")
        for job in jobs:
            if not isinstance(job, dict):
                continue
            serial = str(job.get("ssh_profile", "") or "").strip()
            if not serial:
                continue
            if not _SAFE_PROFILE_ID.fullmatch(serial):
                raise RsyncBoyProfileError(
                    f"RsyncBoy job has an invalid SSH profile id '{serial}'"
                )
            if serial not in refs:
                refs.append(serial)

        if not refs:
            continue

        pool = {}
        for serial in refs:
            pool[serial] = _validate_runtime_profile(
                serial, ssh_namespace.get(serial)
            )
        config["ssh_profiles"] = pool
        injected += len(pool)

    return injected
