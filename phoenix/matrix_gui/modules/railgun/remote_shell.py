"""Fail-closed quoting helpers for MatrixOS SSH launch commands."""

import re
import shlex


_SAFE_REMOTE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def validate_remote_token(value, label):
    """Return a conservative command token or reject it before SSH use."""
    cleaned = str(value or "").strip()
    if not _SAFE_REMOTE_TOKEN.fullmatch(cleaned):
        raise ValueError(
            f"{label} must contain only letters, numbers, '.', '_', or '-' "
            "and be no longer than 128 characters"
        )
    return cleaned


def quote_remote_argument(value, label):
    """Validate required shell data and return its POSIX-quoted form."""
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    if any(control in cleaned for control in ("\x00", "\r", "\n")):
        raise ValueError(f"{label} contains a forbidden control character")
    return shlex.quote(cleaned)
