"""Choose a Qt platform that supports Phoenix's cross-process session tabs."""

import os
import sys


def configure_qt_platform(*, environ=None, platform=None):
    env = os.environ if environ is None else environ
    current_platform = sys.platform if platform is None else platform
    # Preserve explicit overrides (including offscreen test environments).
    if (current_platform.startswith("linux") and not env.get("QT_QPA_PLATFORM")
            and env.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            and env.get("DISPLAY")):
        env["QT_QPA_PLATFORM"] = "xcb"
