"""Offline dialog close regressions; no SSH connection is made."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtGui import QCloseEvent
from matrix_gui.modules.railgun import railgun_check_dialog as module


class CheckLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_all_close_paths_defer_without_waiting_for_worker(self):
        for route in ("reject", "done", "close"):
            with self.subTest(route=route), patch.object(module, "load_registry_ssh_profiles", return_value=[]):
                dialog = module.RailgunCheckDialog()
                worker = Mock()
                worker.isRunning.return_value = True
                dialog._worker = worker
                dialog.show()
                if route == "close":
                    event = QCloseEvent()
                    dialog.closeEvent(event)
                    self.assertFalse(event.isAccepted())
                elif route == "done":
                    dialog.done(QDialog.DialogCode.Rejected)
                else:
                    dialog.reject()
                self.assertTrue(dialog.isVisible())
                worker.requestInterruption.assert_called_once()
                worker.wait.assert_not_called()
                worker.isRunning.return_value = False
                dialog.reject()
                self.assertFalse(dialog.isVisible())
                dialog.deleteLater()

    def test_unexpected_check_and_cleanup_failures_are_reported(self):
        worker = module.RailgunCheckWorker({}, ("ssh",))
        client = Mock()
        client.close.side_effect = RuntimeError("secret-cleanup-payload")
        messages = []
        worker.output.connect(messages.append)
        with patch.object(module, "connect_ssh_profile", return_value=(client, "synthetic-pin")), patch.object(worker, "_check_ssh", side_effect=ValueError("secret-check-payload")):
            worker.run()
        self.assertFalse(worker.success)
        self.assertIsNone(worker.client)
        self.assertTrue(any("ValueError" in message for message in messages))
        self.assertTrue(any("RuntimeError" in message for message in messages))
        self.assertFalse(any("secret-" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
