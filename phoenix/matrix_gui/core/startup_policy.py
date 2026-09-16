"""Session-scoped Phoenix startup capabilities.

The policy is deliberately kept out of the Vault and application settings.  A
new Phoenix process therefore starts locked down every time.  The cockpit
passes the debug choice explicitly to each embedded session process.
"""

from __future__ import annotations

import builtins
import sys
from typing import Any


_ORIGINAL_PRINT_ATTRIBUTE = "_matrixswarm_phoenix_original_print"


_debug_output_enabled = False
_secret_viewing_enabled = False
_close_on_minimize_or_sleep_enabled = False


def configure_startup_policy(
    *,
    allow_secret_viewing: bool = False,
    debug_output: bool = False,
    close_on_minimize_or_sleep: bool = False,
) -> None:
    """Apply capabilities selected during the successful Vault sign-in."""
    global _close_on_minimize_or_sleep_enabled, _secret_viewing_enabled

    _secret_viewing_enabled = bool(allow_secret_viewing)
    _close_on_minimize_or_sleep_enabled = bool(close_on_minimize_or_sleep)
    configure_debug_output(debug_output)


def configure_debug_output(enabled: bool) -> None:
    """Set debug printing for the current process."""
    global _debug_output_enabled

    _debug_output_enabled = bool(enabled)


def reset_startup_policy() -> None:
    """Return Phoenix to its locked-down startup defaults."""
    global _close_on_minimize_or_sleep_enabled, _secret_viewing_enabled

    _secret_viewing_enabled = False
    _close_on_minimize_or_sleep_enabled = False
    configure_debug_output(False)


def debug_output_enabled() -> bool:
    return _debug_output_enabled


def secret_viewing_enabled() -> bool:
    return _secret_viewing_enabled


def close_on_minimize_or_sleep_enabled() -> bool:
    return _close_on_minimize_or_sleep_enabled


def _original_print():
    original = getattr(builtins, _ORIGINAL_PRINT_ATTRIBUTE, None)
    if original is None:
        original = builtins.print
        setattr(builtins, _ORIGINAL_PRINT_ATTRIBUTE, original)
    return original


def guarded_print(*args: Any, **kwargs: Any) -> None:
    """Call Python's original print only while session debugging is enabled."""
    if debug_output_enabled():
        original = _original_print()
        try:
            original(*args, **kwargs)
        except UnicodeEncodeError:
            output = kwargs.get("file") or sys.stdout
            encoding = getattr(output, "encoding", None) or "utf-8"
            safe_args = tuple(
                str(value).encode(encoding, errors="backslashreplace").decode(encoding)
                for value in args
            )
            original(*safe_args, **kwargs)


def install_print_gate() -> None:
    """Install the process-wide gate once, preserving Python's real print."""
    _original_print()
    builtins.print = guarded_print
