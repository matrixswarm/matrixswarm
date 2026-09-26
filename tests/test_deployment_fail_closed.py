"""No remote launch when a required deployment component fails."""
import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from PyQt6.QtWidgets import QApplication
from matrix_gui.swarm_workspace.cls_lib.deployment import deploy_objects as module


class DeploymentFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_required_failure_never_reaches_launch(self):
        for mode in ("invalid", "fetch-error", "empty", "missing-auto-editor"):
            with self.subTest(mode=mode):
                tree = {"root": {"name": "test", "universal_id": "test", "children": [],
                    "config": {}, "constraints": [{"class": "test", "serial": "reference",
                        "required": True, "auto": mode == "missing-auto-editor"}]}}
                before = deepcopy(tree)
                editor = Mock()
                editor.is_autogen.return_value = False
                editor.is_connection.return_value = True
                editor.deploy_fields.return_value = {}
                store = Mock()
                store.get_namespace.return_value = {"reference": {"label": "synthetic"}}
                if mode == "fetch-error":
                    store.get_namespace.side_effect = RuntimeError("SECRET-MARKER")
                resolver = Mock()
                resolver.get.return_value = None if mode == "missing-auto-editor" else editor
                resolver.vcs.get_store.return_value = store
                session = module.DeploymentSession(None, tree, "root", resolver)
                with patch("builtins.print") as output, patch.object(module, "ConstraintValidator") as validator, patch.object(module, "Deploy") as deploy, patch.object(module, "emit_gui_exception_log") as diagnostic, patch("PyQt6.QtWidgets.QMessageBox.critical") as message:
                    validator.return_value.validate.return_value = (mode != "invalid", "invalid")
                    self.assertFalse(session.run("workspace"))
                    deploy.assert_not_called()
                    if diagnostic.called:
                        self.fail(repr(diagnostic.call_args.args[1]))
                    message.assert_called_once()
                    self.assertNotIn("SECRET-MARKER", str(message.call_args))
                    self.assertNotIn("SECRET-MARKER", str(output.call_args_list))
                self.assertEqual(tree, before)

    def test_successful_retry_uses_staging_and_launches_once(self):
        tree = {"root": {"name": "test", "universal_id": "test", "children": [],
            "config": {}, "constraints": [{"class": "test", "serial": "reference",
                "required": True, "raw": {"deployment_only": True}}]}}
        before = deepcopy(tree)
        editor = Mock()
        editor.is_autogen.return_value = False
        editor.is_connection.return_value = True
        editor.deploy_fields.return_value = {"proto": "ssh", "channel": "outgoing.command"}
        store = Mock()
        store.get_namespace.return_value = {"reference": {"label": "synthetic"}}
        resolver = Mock()
        resolver.get.return_value = editor
        resolver.vcs.get_store.return_value = store
        session = module.DeploymentSession(None, tree, "root", resolver)
        with patch("builtins.print"), patch.object(module, "ConstraintValidator") as validator, patch.object(module, "Deploy") as deploy, patch("PyQt6.QtWidgets.QMessageBox.critical"), patch.object(module, "inject_rsync_boy_ssh_profiles", return_value=0):
            validator.return_value.validate.return_value = (False, "invalid")
            self.assertFalse(session.run("workspace"))
            deploy.assert_not_called()
            validator.return_value.validate.return_value = (True, "valid")
            deploy.return_value.deploy_directive.return_value = True
            self.assertTrue(session.run("workspace"))
            deploy.return_value.deploy_directive.assert_called_once()
            # A user cancellation in the preparation dialogs must propagate
            # back to the caller rather than being reported as success.
            deploy.return_value.deploy_directive.return_value = False
            self.assertFalse(session.run("workspace"))
        self.assertEqual(tree, before)


if __name__ == "__main__":
    unittest.main()
