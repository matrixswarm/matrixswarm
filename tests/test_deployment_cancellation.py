"""Preparation cancellation must neither persist nor start a remote launch."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from PyQt6.QtWidgets import QApplication, QDialog
from matrix_gui.swarm_workspace.cls_lib.deployment import deploy as module


class CancellationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cancel_each_preparation_dialog(self):
        for phase in ("label", "options", "sources", "preview", "save-rejected", "success"):
            with self.subTest(phase=phase):
                vault = Mock()
                vault.data = {"deployments": {"existing": {"label": "keep"}}}
                vault.patch.return_value = phase != "save-rejected"
                vault.get_store.return_value.get_namespace.return_value = {}
                opts = {"clown_car": phase == "sources", "universe": "test", "linux_user": "matrix-test", "railgun_target": {"serial": "synthetic"}}
                with patch.object(module.VaultCoreSingleton, "get", return_value=vault), patch.object(module.QInputDialog, "getText", return_value=("test", phase != "label")), patch.object(module, "DeployOptionsDialog") as options, patch.object(module, "AgentRootValidator") as sources, patch.object(module, "EncryptionStagingDialog") as preview, patch.object(module, "generate_swarm_encrypted_directive", return_value=({}, b"synthetic", "hash")), patch.object(module, "derive_runtime_capabilities", return_value={}), patch.object(module.RailgunDialog, "launch") as launch, patch.object(module.QMessageBox, "information"), patch.object(module.QMessageBox, "critical"), patch("builtins.print"):
                    options.return_value.exec.return_value = QDialog.DialogCode.Rejected if phase == "options" else QDialog.DialogCode.Accepted
                    options.return_value.get_options.return_value = opts
                    sources.return_value.run.return_value = None
                    preview.return_value.exec.return_value = QDialog.DialogCode.Rejected if phase == "preview" else QDialog.DialogCode.Accepted
                    result = module.Deploy().deploy_directive(None, {"agents": {}}, SimpleNamespace(deployment={"agents": [], "certs": {}}), "workspace")
                    self.assertIs(result, phase == "success")
                    if phase == "success":
                        launch.assert_called_once()
                        saved = next(record for key, record in vault.patch.call_args.args[1].items() if key != "existing")
                        for key, value in saved["railgun_boot_options"].items():
                            self.assertEqual(value, launch.call_args.args[-1].get(key))
                        self.assertEqual(saved["railgun_request_id"], saved["railgun_boot_options"]["railgun_request_id"])
                    else:
                        launch.assert_not_called()
                    if phase not in ("success", "save-rejected"):
                        vault.patch.assert_not_called()
                    self.assertEqual(vault.data, {"deployments": {"existing": {"label": "keep"}}})


if __name__ == "__main__":
    unittest.main()
