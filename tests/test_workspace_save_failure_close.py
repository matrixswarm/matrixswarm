"""Closing a workspace after a failed vault write requires explicit discard."""
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QPushButton
from matrix_gui.swarm_workspace.swarm_workspace import SwarmWorkspaceDialog


class WorkspaceFailureCloseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = SwarmWorkspaceDialog.__new__(SwarmWorkspaceDialog)
        QDialog.__init__(self.dialog)
        self.dialog._ready_timer = QTimer(self.dialog)
        self.dialog._slow_save_timer = QTimer(self.dialog)
        self.dialog.save_status = QLabel(self.dialog)
        self.dialog.retry_save_btn = QPushButton(self.dialog)
        self.dialog._saving = False
        self.dialog._save_error = False
        self.dialog._close_requested = False
        self.dialog._allow_close = False
        self.dialog._pending_entry = None
        self.dialog._saved_entry = {"label": "saved"}
        self.dialog._snapshot_entry = Mock(return_value={"label": "changed"})
        self.dialog._vault_core = SimpleNamespace(_closed=False)
        self.dialog._save_failed()

    def test_failed_save_offers_safe_default_and_cancel_keeps_editor(self):
        event = QCloseEvent()
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Cancel) as warning:
            self.dialog.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertEqual(warning.call_args.args[-1], QMessageBox.StandardButton.Cancel)
        self.assertIn("discard unsaved changes", self.dialog.save_status.text())
        self.assertEqual(self.dialog._snapshot_entry()["label"], "changed")

    def test_explicit_discard_closes_without_another_write(self):
        event = QCloseEvent()
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Discard), patch.object(self.dialog, "save") as save:
            self.dialog.closeEvent(event)
        self.assertTrue(event.isAccepted())
        save.assert_not_called()

    def test_inflight_save_still_defers_close(self):
        self.dialog._saving = True
        event = QCloseEvent()
        with patch.object(QMessageBox, "warning") as warning, patch.object(self.dialog, "save") as save:
            self.dialog.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertTrue(self.dialog._close_requested)
        warning.assert_not_called()
        save.assert_called_once()

    def test_successful_retry_clears_error_and_allows_normal_close(self):
        entry = {"label": "changed"}
        with patch("matrix_gui.swarm_workspace.swarm_workspace.VaultCoreSingleton.get", return_value=self.dialog._vault_core):
            self.dialog._save_completed(entry, True)
        self.assertFalse(self.dialog._save_error)
        event = QCloseEvent()
        with patch.object(QMessageBox, "warning") as warning:
            self.dialog.closeEvent(event)
        self.assertTrue(event.isAccepted())
        warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
