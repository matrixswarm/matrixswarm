"""Validated systemd command builders for least-privilege watchdog agents."""

import re


_SYSTEMD_UNIT = re.compile(r"[A-Za-z0-9_.@-]+\.service\Z")
SYSTEMCTL = "/usr/bin/systemctl"
SUDO = "/usr/bin/sudo"


def normalize_systemd_unit(service_name):
    """Return a canonical ``*.service`` unit or reject unsafe configuration."""
    unit = str(service_name or "").strip()
    if not unit.endswith(".service"):
        unit += ".service"
    if not _SYSTEMD_UNIT.fullmatch(unit):
        raise ValueError(f"Invalid systemd service unit: {service_name!r}")
    return unit


def status_command(service_name):
    """Build an unprivileged, non-interactive service health command."""
    return [SYSTEMCTL, "is-active", "--quiet", normalize_systemd_unit(service_name)]


def restart_command(service_name):
    """Build the exact command matched by Railgun's narrow sudoers grant."""
    return [
        SUDO,
        "-n",
        SYSTEMCTL,
        "restart",
        normalize_systemd_unit(service_name),
    ]


def diagnostic_command(service_name):
    """Build a non-paged status command suitable for captured diagnostics."""
    return [
        SYSTEMCTL,
        "status",
        "--no-pager",
        normalize_systemd_unit(service_name),
    ]
