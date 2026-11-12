"""Deployment preparation must show progress and report early failures."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QProgressDialog, QWidget
from matrix_gui.swarm_workspace import swarm_workspace as workspace
from matrix_gui.swarm_workspace.cls_lib.deployment import deploy_objects as deploy


class DeploymentFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_progress_is_visible_during_resolution_and_closed_before_error(self):
        parent = QWidget()
        parent.show()
        session = deploy.DeploymentSession(parent, {"root": {"name": "matrix"}}, "root", Mock())
        def fail(tree):
            self.assertIsInstance(session._progress, QProgressDialog)
            self.assertTrue(session._progress.isVisible())
            raise deploy.ManualConstraintFailure("Required constraint is missing")
        with patch.object(session, "_resolve_constraints_parallel", side_effect=fail), patch.object(QMessageBox, "critical") as error:
            self.assertFalse(session.run("workspace"))
        self.assertIsNone(session._progress)
        self.assertIn("Required constraint is missing", error.call_args.args[2])
        parent.close()

    def test_failed_or_inflight_save_blocks_deploy_with_explanation(self):
        dialog = workspace.SwarmWorkspaceDialog.__new__(workspace.SwarmWorkspaceDialog)
        QDialog.__init__(dialog)
        dialog.controller = Mock()
        for saving, failed in ((True, False), (False, True)):
            dialog._saving, dialog._save_error = saving, failed
            with patch.object(QMessageBox, "warning") as warning:
                dialog.on_deploy_clicked()
            warning.assert_called_once()
        dialog.controller.export_agent_tree.assert_not_called()

    def test_unexpected_preparation_error_is_visible(self):
        dialog = workspace.SwarmWorkspaceDialog.__new__(workspace.SwarmWorkspaceDialog)
        QDialog.__init__(dialog)
        dialog._saving = dialog._save_error = False
        dialog.controller = Mock()
        dialog.controller.export_agent_tree.side_effect = RuntimeError("test")
        with patch.object(QMessageBox, "critical") as error, patch.object(workspace, "emit_gui_exception_log") as log:
            dialog.on_deploy_clicked()
        error.assert_called_once()
        log.assert_called_once()


if __name__ == "__main__":
    unittest.main()
