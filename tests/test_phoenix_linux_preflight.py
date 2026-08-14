import ast
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
    XCB_CURSOR_LIBRARY,
    require_linux_gui_runtime,
    require_linux_egl,
)


class PhoenixLinuxPreflightTests(unittest.TestCase):
    def test_non_linux_platform_skips_gui_runtime_probe(self):
        def unexpected_loader(_name):
            self.fail("Linux GUI libraries must not be probed outside Linux")

        require_linux_gui_runtime(platform="win32", loader=unexpected_loader)

    def test_linux_probe_loads_the_versioned_gui_libraries(self):
        loaded = []

        require_linux_gui_runtime(platform="linux", loader=loaded.append)

        self.assertEqual([EGL_LIBRARY, XCB_CURSOR_LIBRARY], loaded)

    def test_missing_gui_library_exits_with_actionable_package_commands(self):
        def missing_loader(name):
            if name == XCB_CURSOR_LIBRARY:
                raise OSError("not found")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                require_linux_gui_runtime(platform="linux", loader=missing_loader)

        self.assertEqual(PREFLIGHT_EXIT_CODE, raised.exception.code)
        message = stderr.getvalue()
        self.assertIn(XCB_CURSOR_LIBRARY, message)
        self.assertIn("sudo apt install -y libegl1 libxcb-cursor0", message)
        self.assertIn("sudo dnf install -y libglvnd-egl xcb-util-cursor", message)

    def test_original_egl_only_preflight_remains_compatible(self):
        loaded = []

        require_linux_egl(platform="linux", loader=loaded.append)

        self.assertEqual([EGL_LIBRARY], loaded)

    def test_phoenix_runs_preflight_before_any_pyqt_import(self):
        source = (PHOENIX_ROOT / "phoenix.py").read_text(encoding="utf-8")

        self.assertLess(
            source.index("require_linux_gui_runtime()"),
            source.index("from PyQt6"),
        )

    def test_winsound_is_imported_only_inside_the_windows_branch(self):
        panel_path = (
            PHOENIX_ROOT
            / "matrix_gui/core/panel/home/phoenix_static_panel.py"
        )
        source = panel_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        top_level_imports = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertNotIn("winsound", top_level_imports)
        self.assertIn('if platform.system() == "Windows":', source)
        self.assertIn("                    import winsound", source)

    def test_readme_documents_the_linux_runtime_prerequisite(self):
        readme = (PHOENIX_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn(EGL_LIBRARY, readme)
        self.assertIn(XCB_CURSOR_LIBRARY, readme)
        self.assertIn("sudo apt install -y libegl1 libxcb-cursor0", readme)
        self.assertIn("sudo dnf install -y libglvnd-egl xcb-util-cursor", readme)


if __name__ == "__main__":
    unittest.main()
