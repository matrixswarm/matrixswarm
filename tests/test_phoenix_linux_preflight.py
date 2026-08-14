import contextlib
import io
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PHOENIX_ROOT = ROOT / "phoenix"
sys.path.insert(0, str(PHOENIX_ROOT))

from matrix_gui.core.utils.linux_gui_preflight import (  # noqa: E402
    EGL_LIBRARY,
    PREFLIGHT_EXIT_CODE,
    require_linux_egl,
)


class PhoenixLinuxPreflightTests(unittest.TestCase):
    def test_non_linux_platform_skips_egl_probe(self):
        def unexpected_loader(_name):
            self.fail("EGL must not be probed outside Linux")

        require_linux_egl(platform="win32", loader=unexpected_loader)

    def test_linux_probe_loads_the_versioned_egl_library(self):
        loaded = []

        require_linux_egl(platform="linux", loader=loaded.append)

        self.assertEqual([EGL_LIBRARY], loaded)

    def test_missing_egl_exits_with_actionable_package_commands(self):
        def missing_loader(_name):
            raise OSError("not found")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                require_linux_egl(platform="linux", loader=missing_loader)

        self.assertEqual(PREFLIGHT_EXIT_CODE, raised.exception.code)
        message = stderr.getvalue()
        self.assertIn(EGL_LIBRARY, message)
        self.assertIn("sudo apt install -y libegl1", message)
        self.assertIn("sudo dnf install -y libglvnd-egl", message)

    def test_phoenix_runs_preflight_before_any_pyqt_import(self):
        source = (PHOENIX_ROOT / "phoenix.py").read_text(encoding="utf-8")

        self.assertLess(
            source.index("require_linux_egl()"),
            source.index("from PyQt6"),
        )

    def test_readme_documents_the_linux_runtime_prerequisite(self):
        readme = (PHOENIX_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn(EGL_LIBRARY, readme)
        self.assertIn("sudo apt install -y libegl1", readme)
        self.assertIn("sudo dnf install -y libglvnd-egl", readme)


if __name__ == "__main__":
    unittest.main()
