"""Password rotation must not race accepted writes or overwrite failed decryptions."""
import sys
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from matrix_gui.modules.vault import vault_service as service

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
from matrix_gui.modules.vault.vault_change_password_dialog import VaultChangePasswordDialog
from matrix_gui.modules.vault.vault_create_dialog import VaultCreateDialog
from matrix_gui.modules.vault.vault_unlock_dialog import VaultUnlockDialog


class RotationDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_late_hardware_callbacks_after_cancel_cannot_rotate(self):
        dialog = VaultChangePasswordDialog()
        dialog._pending_credentials = {"old": "old", "new": "new"}
        dialog._pending_factors = ["old"]
        dialog.reject()
        with patch.object(service.VaultService, "change_password") as rotate, patch.object(QMessageBox, "warning") as warning:
            dialog._on_yubikey_ready("late-secret", "serial")
            dialog._on_yubikey_failed("late failure")
            dialog._finish_change()
            rotate.assert_not_called()
            warning.assert_not_called()
        self.assertIsNone(dialog._pending_credentials)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        dialog.deleteLater()

    def test_create_and_unlock_ignore_ready_after_cancel(self):
        for cls, operation in ((VaultCreateDialog, "_save_with_password"), (VaultUnlockDialog, "_attempt_unlock")):
            with self.subTest(dialog=cls.__name__):
                dialog = cls()
                dialog.reject()
                with patch.object(dialog, operation) as action, patch.object(QMessageBox, "warning") as warning:
                    dialog._on_yubikey_ready("late-test-secret", "serial")
                    dialog._on_yubikey_failed("late failure")
                    action.assert_not_called()
                    warning.assert_not_called()
                dialog.deleteLater()

    def test_unlock_rejects_non_dictionary_decryption(self):
        for value in (None, [], "unexpected"):
            with self.subTest(value=value):
                dialog = VaultUnlockDialog()
                dialog.vault_path = "test-only.json"
                with patch.object(service.VaultService, "load_vault", return_value=value), patch.object(QMessageBox, "warning") as warning:
                    dialog._attempt_unlock("test-only-password")
                    self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
                    self.assertIsNone(dialog.vault_password)
                    self.assertTrue(warning.called)
                dialog.deleteLater()

    def test_create_path_preparation_error_is_contained(self):
        dialog = VaultCreateDialog()
        with patch("matrix_gui.modules.vault.vault_create_dialog.resolve_matrixswarm_base", side_effect=PermissionError("private-data")), \
             patch.object(QMessageBox, "critical") as critical:
            dialog._save_with_password("test-only-password")
            self.assertTrue(critical.called)
            self.assertIsNone(dialog.vault_password)
            self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        dialog.deleteLater()

    def test_write_failure_is_not_reported_as_wrong_password(self):
        dialog = VaultChangePasswordDialog()
        dialog.vault_path = "test-only.json"
        dialog._pending_credentials = {"old": "old", "new": "new"}
        with patch.object(service.VaultService, "change_password", side_effect=PermissionError("SECRET-MARKER")), \
             patch.object(QMessageBox, "critical") as critical, patch.object(QMessageBox, "information") as success:
            dialog._finish_change()
            message = str(critical.call_args)
            self.assertIn("PermissionError", message)
            self.assertNotIn("credential is incorrect", message)
            self.assertNotIn("SECRET-MARKER", message)
            success.assert_not_called()
        self.assertIsNone(dialog.result_password)
        self.assertIsNone(dialog._pending_credentials)
        dialog._pending_credentials = {"old": "old", "new": "new"}
        with patch.object(service.VaultService, "change_password", return_value={"registry": {}}), patch.object(QMessageBox, "information"):
            dialog._finish_change()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.result_password, "new")
        dialog.deleteLater()


class RotationGuardTests(unittest.TestCase):
    def test_active_or_draining_vault_blocks_rotation_before_io(self):
        path = Path("test-only-vault.json").resolve()
        for closed, active, queue in ((False, None, []), (True, object(), []), (True, None, [object()])):
            with self.subTest(closed=closed, active=bool(active), queued=bool(queue)):
                core = SimpleNamespace(vault_path=path, _closed=closed,
                                       _workspace_active=active, _workspace_queue=queue)
                with patch.object(service.VaultCoreSingleton, "_instance", core), \
                     patch.object(service, "load_vault_singlefile") as load, \
                     patch.object(service, "save_vault_singlefile") as save:
                    with self.assertRaises(service.VaultBusyError):
                        service.VaultService.change_password(str(path), "old", "new")
                    load.assert_not_called()
                    save.assert_not_called()

    def test_failed_decryption_never_writes(self):
        for invalid in (False, None, [], "bad"):
            with self.subTest(invalid=invalid), patch.object(service.VaultCoreSingleton, "_instance", None), \
                 patch.object(service, "load_vault_singlefile", return_value=invalid), \
                 patch.object(service, "save_vault_singlefile") as save:
                with self.assertRaises(ValueError):
                    service.VaultService.change_password("test-only-vault.json", "wrong", "new")
                save.assert_not_called()

    def test_closed_drained_vault_rotates(self):
        path = Path("test-only-vault.json").resolve()
        core = SimpleNamespace(vault_path=path, _closed=True, _workspace_active=None, _workspace_queue=[])
        data = {"registry": {}}
        with patch.object(service.VaultCoreSingleton, "_instance", core), \
             patch.object(service, "load_vault_singlefile", return_value=data), \
             patch.object(service, "save_vault_singlefile") as save:
            self.assertEqual(service.VaultService.change_password(str(path), "old", "new"), data)
            save.assert_called_once_with(data, "new", str(path))
