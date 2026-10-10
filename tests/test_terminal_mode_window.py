"""Terminal setup is window-scoped and never starts a runtime or grants access."""
import io
import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))

from PyQt6.QtWidgets import QApplication
from matrix_gui.core.dialog import terminal_mode_dialog as module
from matrix_gui.core.event_bus import EventBus
from matrix_gui.core.phoenix_control_panel import PhoenixControlPanel


class VaultFixture:
    def __init__(self):
        self.data = {"deployments": {"fixture": {"label": "Fixture"}}}
        self.writes = []

    def read(self):
        return deepcopy(self.data)

    def patch(self, key, value):
        self.writes.append((key, value))
        self.data[key] = deepcopy(value)
        return True


class TerminalModeWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self):
        authority = VaultFixture()
        dialog = module.TerminalModeDialog(vault_authority=authority)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.reject)
        return dialog, authority

    def test_separate_window_shows_controls_without_changing_policy(self):
        dialog, authority = self.dialog()
        dialog.show()
        self.app.processEvents()
        self.assertEqual("Terminal Mode", dialog.windowTitle())
        self.assertTrue(dialog.controls.isVisible())
        self.assertFalse(dialog.controls.enabled_checkbox.isChecked())
        self.assertFalse(any(item.isChecked() for item in dialog.controls.operation_checkboxes.values()))
        self.assertEqual([], authority.writes)

    def test_route_editor_receives_explicit_terminal_context(self):
        dialog, authority = self.dialog()
        with patch.object(module, "RegistryManagerDialog") as editor:
            dialog.routes_button.click()
        editor.assert_called_once_with(dialog, class_lock="matrix_ssh", terminal_mode=True)
        editor.return_value.exec.assert_called_once()
        editor.return_value.deleteLater.assert_called_once()
        self.assertEqual([], authority.writes)

    def test_vault_close_closes_setup_and_removes_subscription(self):
        dialog, _ = self.dialog()
        dialog.show()
        with io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict") as stdout:
            with patch.object(sys, "stdout", stdout), patch.object(EventBus, "off", wraps=EventBus.off) as unsubscribe:
                EventBus.emit("vault.closed")
        self.assertFalse(dialog.isVisible())
        unsubscribe.assert_any_call("vault.closed", dialog._vault_closed)

    def test_vault_close_closes_all_setup_windows(self):
        first, _ = self.dialog()
        second, _ = self.dialog()
        first.show()
        second.show()
        EventBus.emit("vault.closed")
        self.assertFalse(first.isVisible())
        self.assertFalse(second.isVisible())
        listeners = EventBus._listeners.get("vault.closed", [])
        self.assertNotIn(first._vault_closed, listeners)
        self.assertNotIn(second._vault_closed, listeners)

    def test_top_bar_opens_ai_mode_with_a_white_icon(self):
        panel = PhoenixControlPanel()
        self.addCleanup(panel.deleteLater)
        self.addCleanup(EventBus.off, "vault.unlocked", panel.on_vault_unlocked)
        self.addCleanup(EventBus.off, "vault.update", panel.on_vault_update)
        self.assertEqual("AI Mode", panel.terminal_btn.text())
        self.assertFalse(panel.terminal_btn.icon().isNull())
        with patch("matrix_gui.modules.access_control.access_control_dialog.AccessControlDialog") as dialog:
            panel.terminal_btn.click()
        dialog.assert_called_once_with(panel)
        dialog.return_value.exec.assert_called_once()
        dialog.return_value.deleteLater.assert_called_once()
        source = (ROOT / "phoenix/matrix_gui/core/panel/home/phoenix_static_panel.py").read_text(encoding="utf-8")
        self.assertNotIn("TerminalAccessControls", source)


if __name__ == "__main__":
    unittest.main()
