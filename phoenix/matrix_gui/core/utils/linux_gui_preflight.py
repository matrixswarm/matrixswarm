"""Fail early with actionable guidance when Phoenix lacks Linux EGL."""

import ctypes
import sys


EGL_LIBRARY = "libEGL.so.1"
PREFLIGHT_EXIT_CODE = 78


def require_linux_egl(*, platform=None, loader=ctypes.CDLL):
    """Require the EGL runtime before importing PyQt6 on Linux."""
    current_platform = sys.platform if platform is None else platform
    if not current_platform.startswith("linux"):
        return

    try:
        loader(EGL_LIBRARY)
    except OSError:
        print(
            "[PHOENIX][PREFLIGHT] Phoenix cannot start because the Linux "
            f"runtime library {EGL_LIBRARY} is missing.\n"
            "Install it, then launch Phoenix again:\n"
            "  Ubuntu/Debian: sudo apt update && sudo apt install -y libegl1\n"
            "  Fedora/RHEL/Rocky/Alma: sudo dnf install -y libglvnd-egl",
            file=sys.stderr,
        )
        raise SystemExit(PREFLIGHT_EXIT_CODE) from None
