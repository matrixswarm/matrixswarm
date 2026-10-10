"""Vault capability UI: real Qt widgets and synthetic unlock responses."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from PyQt6.QtWidgets import QApplication, QCheckBox, QDialog, QLabel
from matrix_gui.core import startup_policy as policy
from matrix_gui.modules.vault.vault_unlock_dialog import VaultUnlockDialog
from matrix_gui.modules.vault.vault_service import VaultService


class VaultCapabilitySessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        policy.reset_startup_policy()
        self.addCleanup(policy.reset_startup_policy)
        self.dialog = VaultUnlockDialog()
        self.addCleanup(self.dialog.deleteLater)

    def test_optional_section_is_static_and_all_four_choices_are_off(self):
        self.assertFalse(self.dialog.optional_capabilities.isHidden())
        choices = self.dialog.optional_capabilities.findChildren(QCheckBox)
        self.assertEqual(4, len(choices))
        self.assertIn(self.dialog.ai_mode_checkbox, choices)
        self.assertTrue(all(not item.isChecked() for item in choices))
        self.assertFalse(hasattr(self.dialog, "capabilities_toggle"))
        self.assertFalse(hasattr(self.dialog, "llm_record_mode_checkbox"))

    def test_changing_capabilities_keeps_the_section_and_heading_visible(self):
        heading = next(item for item in self.dialog.findChildren(QLabel)
                       if item.text() == "Optional capabilities for this session:")
        self.dialog.debug_output_checkbox.click()
        self.dialog.close_on_minimize_or_sleep_checkbox.click()
        self.assertFalse(self.dialog.optional_capabilities.isHidden())
        self.assertEqual("Optional capabilities for this session:", heading.text())
        self.assertTrue(self.dialog.debug_output)
        self.assertTrue(self.dialog.close_on_minimize_or_sleep)
        self.assertFalse(policy.debug_output_enabled())

    def test_canceled_dialog_does_not_apply_or_inherit_capabilities(self):
        self.dialog.debug_output_checkbox.setChecked(True)
        self.dialog.cancel_btn.click()
        self.assertEqual(QDialog.DialogCode.Rejected, self.dialog.result())
        next_login = VaultUnlockDialog()
        self.addCleanup(next_login.deleteLater)
        self.assertFalse(next_login.debug_output)
        self.assertFalse(next_login.optional_capabilities.isHidden())

    def test_failed_unlock_then_success_returns_choice_but_only_cockpit_applies_it(self):
        self.dialog.vault_path = "synthetic-not-a-real-vault.json"
        self.dialog.pass_input.setText("synthetic-password")
        self.dialog.debug_output_checkbox.setChecked(True)
        with patch.object(VaultService, "load_vault", return_value=False), \
             patch("matrix_gui.modules.vault.vault_unlock_dialog.QMessageBox.warning"):
            self.dialog.unlock_btn.click()
        self.assertNotEqual(QDialog.DialogCode.Accepted, self.dialog.result())
        with patch.object(VaultService, "load_vault", return_value={"deployments": {}}):
            self.dialog.unlock_btn.click()
        self.assertEqual(QDialog.DialogCode.Accepted, self.dialog.result())
        self.assertTrue(self.dialog.debug_output)
        self.assertFalse(policy.debug_output_enabled())

    def test_hardware_unlock_freezes_capabilities_until_finished(self):
        self.dialog._set_yubikey_busy(True, "Synthetic hardware wait")
        choices = self.dialog.optional_capabilities.findChildren(QCheckBox)
        self.assertTrue(all(not item.isEnabled() for item in choices))
        self.dialog._set_yubikey_busy(False, "")
        self.assertTrue(all(item.isEnabled() for item in choices))



if __name__ == "__main__":
    unittest.main()
