"""Fail early with actionable guidance when Phoenix lacks Linux GUI libraries."""

import ctypes
import sys


EGL_LIBRARY = "libEGL.so.1"
XCB_CURSOR_LIBRARY = "libxcb-cursor.so.0"
LINUX_GUI_LIBRARIES = (EGL_LIBRARY, XCB_CURSOR_LIBRARY)
PREFLIGHT_EXIT_CODE = 78


def _require_linux_libraries(libraries, *, platform=None, loader=ctypes.CDLL):
    current_platform = sys.platform if platform is None else platform
    if not current_platform.startswith("linux"):
        return

    missing = []
    for library in libraries:
        try:
            loader(library)
        except OSError:
            missing.append(library)

    if missing:
        print(
            "[PHOENIX][PREFLIGHT] Phoenix cannot start because the Linux "
            f"GUI runtime is missing: {', '.join(missing)}.\n"
            "Install the required packages, then launch Phoenix again:\n"
            "  Ubuntu/Debian: sudo apt update && sudo apt install -y "
            "libegl1 libxcb-cursor0\n"
            "  Fedora/RHEL/Rocky/Alma: sudo dnf install -y "
            "libglvnd-egl xcb-util-cursor",
            file=sys.stderr,
        )
        raise SystemExit(PREFLIGHT_EXIT_CODE) from None


def require_linux_gui_runtime(*, platform=None, loader=ctypes.CDLL):
    """Require Phoenix's native Qt runtime libraries on Linux."""
    _require_linux_libraries(
        LINUX_GUI_LIBRARIES,
        platform=platform,
        loader=loader,
    )


def require_linux_egl(*, platform=None, loader=ctypes.CDLL):
    """Retain the original EGL-only preflight API for compatibility."""
    _require_linux_libraries(
        (EGL_LIBRARY,),
        platform=platform,
        loader=loader,
    )
