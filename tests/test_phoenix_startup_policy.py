import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PHOENIX_ROOT = ROOT / "phoenix"
sys.path.insert(0, str(PHOENIX_ROOT))

from matrix_gui.core.startup_policy import (  # noqa: E402
    close_on_minimize_or_sleep_enabled,
    configure_startup_policy,
    debug_output_enabled,
    reset_startup_policy,
    secret_viewing_enabled,
)


class PhoenixStartupPolicyTests(unittest.TestCase):
    def tearDown(self):
        reset_startup_policy()

    def test_startup_capabilities_default_off_and_reset_to_off(self):
        reset_startup_policy()
        self.assertFalse(secret_viewing_enabled())
        self.assertFalse(debug_output_enabled())
        self.assertFalse(close_on_minimize_or_sleep_enabled())

        configure_startup_policy(
            allow_secret_viewing=True,
            debug_output=True,
            close_on_minimize_or_sleep=True,
        )
        self.assertTrue(secret_viewing_enabled())
        self.assertTrue(debug_output_enabled())
        self.assertTrue(close_on_minimize_or_sleep_enabled())

        reset_startup_policy()
        self.assertFalse(secret_viewing_enabled())
        self.assertFalse(debug_output_enabled())
        self.assertFalse(close_on_minimize_or_sleep_enabled())

    def test_print_gate_suppresses_output_until_debug_is_enabled(self):
        script = """
from matrix_gui.core.startup_policy import (
    configure_debug_output,
    install_print_gate,
)
install_print_gate()
print('hidden')
configure_debug_output(True)
print('visible')
configure_debug_output(False)
print('hidden-again')
"""
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(PHOENIX_ROOT)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            check=True,
            env=environment,
            text=True,
        )
        self.assertEqual("visible", result.stdout.strip())

    def test_print_gate_survives_console_encoding_errors(self):
        script = """
import io
from matrix_gui.core.startup_policy import (
    configure_debug_output,
    install_print_gate,
)
raw = io.BytesIO()
limited_console = io.TextIOWrapper(raw, encoding='ascii')
install_print_gate()
configure_debug_output(True)
print('Victory ⚠', file=limited_console)
limited_console.flush()
assert raw.getvalue().replace(b'\\r\\n', b'\\n') == b'Victory \\u26a0\\n'
"""
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(PHOENIX_ROOT)
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            check=True,
            env=environment,
            text=True,
        )

    def test_environment_cannot_bypass_debug_default(self):
        script = """
from matrix_gui.core.startup_policy import install_print_gate
install_print_gate()
print('must-remain-hidden')
"""
        environment = os.environ.copy()
        environment["MATRIXSWARM_PHOENIX_DEBUG"] = "1"
        environment["PYTHONPATH"] = str(PHOENIX_ROOT)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            check=True,
            env=environment,
            text=True,
        )
        self.assertEqual("", result.stdout.strip())

    def test_phoenix_installs_print_gate_before_ui_imports_and_prints(self):
        source = (PHOENIX_ROOT / "phoenix.py").read_text(encoding="utf-8")
        install_position = source.index("install_print_gate()")
        self.assertLess(install_position, source.index("require_linux_gui_runtime()"))
        self.assertLess(install_position, source.index('print("Python:"'))
        self.assertLess(install_position, source.index("from PyQt6"))

    def test_unlock_options_are_explicitly_off_by_default(self):
        source = (
            PHOENIX_ROOT
            / "matrix_gui/modules/vault/vault_unlock_dialog.py"
        ).read_text(encoding="utf-8")
        self.assertIn("self.allow_secret_viewing_checkbox.setChecked(False)", source)
        self.assertIn("self.debug_output_checkbox.setChecked(False)", source)
        self.assertIn(
            "self.close_on_minimize_or_sleep_checkbox.setChecked(False)",
            source,
        )

    def test_secret_actions_are_hidden_and_guarded(self):
        source = (
            PHOENIX_ROOT
            / "matrix_gui/modules/directive/directive_manager_dialog.py"
        ).read_text(encoding="utf-8")
        self.assertEqual(2, source.count("setVisible(secret_viewing_enabled())"))
        self.assertGreaterEqual(
            source.count("if not secret_viewing_enabled():"),
            2,
        )

    def test_session_process_receives_the_debug_choice(self):
        cockpit = (PHOENIX_ROOT / "phoenix.py").read_text(encoding="utf-8")
        session = (
            PHOENIX_ROOT / "matrix_gui/core/session_window.py"
        ).read_text(encoding="utf-8")
        self.assertIn("args=(session_id, child_conn, debug_output_enabled())", cockpit)
        self.assertIn("def run_session(session_id, conn, debug_output=False):", session)
        self.assertIn("configure_debug_output(debug_output)", session)

    def test_failed_unlock_runtime_resets_selected_capabilities(self):
        cockpit = (PHOENIX_ROOT / "phoenix.py").read_text(encoding="utf-8")
        unlock_exception = cockpit.index(
            'emit_gui_exception_log("PhoenixCockpit.unlock_vault", e)'
        )
        reset_before_exception = cockpit.rfind(
            "reset_startup_policy()",
            0,
            unlock_exception,
        )
        self.assertGreater(reset_before_exception, cockpit.index("def unlock_vault"))

    def test_security_shutdown_covers_minimize_and_sleep(self):
        cockpit = (PHOENIX_ROOT / "phoenix.py").read_text(encoding="utf-8")
        self.assertIn("QEvent.Type.WindowStateChange", cockpit)
        self.assertIn("Qt.ApplicationState.ApplicationSuspended", cockpit)
        self.assertIn("kernel32.GetTickCount64", cockpit)
        self.assertIn("kernel32.QueryUnbiasedInterruptTime", cockpit)
        self.assertIn("def _check_for_system_sleep(self):", cockpit)
        self.assertIn("if suspended_elapsed >= 2.0:", cockpit)
        self.assertIn('self._request_security_shutdown("cockpit minimized")', cockpit)
        self.assertIn("QTimer.singleShot(0, app.quit)", cockpit)


if __name__ == "__main__":
    unittest.main()
