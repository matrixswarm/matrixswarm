"""Offline composed route: reference persistence, validation, private compilation."""
import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from PyQt6.QtWidgets import QApplication
from matrix_gui.registry.object_classes import EDITOR_REGISTRY, PROVIDER_REGISTRY
from matrix_gui.registry.object_classes.editors.matrix_ssh import MatrixSSH
from matrix_gui.swarm_workspace.cls_lib.constraint.constraint_object import Constraint
from matrix_gui.swarm_workspace.cls_lib.deployment.deployment_compiler import DeploymentCompiler


class MatrixSSHAssignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.records = {"a" * 32: dict(serial="a" * 32, label="synthetic",
            host="example.invalid", port=22, username="tester", auth_type="password",
            password="synthetic-secret", trusted_host_fingerprint="SHA256:" + "A" * 43)}
        self.patch = patch.object(MatrixSSH, "_ssh_records", return_value=self.records)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.editor = MatrixSSH()
        self.addCleanup(self.editor.deleteLater)

    def test_discovery_and_required_selection(self):
        self.assertIs(EDITOR_REGISTRY["matrix_ssh"], MatrixSSH)
        self.assertIn("matrix_ssh", PROVIDER_REGISTRY)
        self.assertFalse(self.editor.is_validated()[0])
        with self.assertRaises(ValueError):
            self.editor.deploy_fields()

    def test_reference_round_trip_and_private_route(self):
        before = deepcopy(self.records)
        self.editor.ssh.setCurrentIndex(1)
        self.editor.default_outgoing.setChecked(True)
        saved = self.editor.serialize()
        self.assertEqual(saved["ssh_serial"], "a" * 32)
        self.assertNotIn("password", saved)
        self.editor.on_load(saved)
        self.assertTrue(self.editor.is_validated()[0])
        fields = self.editor.deploy_fields()
        constraint = Constraint("matrix_ssh", self.editor, {})
        constraint.fields = fields
        ir = SimpleNamespace(name="matrix_ssh", universal_id="test-ssh", children=[],
            node={"config": {}}, resolved={"matrix_ssh": constraint})
        compiled = DeploymentCompiler({"root": ir}, "root").compile()
        connection = compiled["agents"]["connection"]
        self.assertEqual(connection["channel"], "outgoing.command")
        self.assertEqual(connection["proto"], "ssh")
        self.assertTrue(connection["default_outgoing"])
        self.assertEqual(compiled["certs"], {})
        self.assertEqual(before, self.records)

    def test_deleted_reference_and_invalid_channel_fail_closed(self):
        self.editor.ssh.setCurrentIndex(1)
        saved = self.editor.serialize()
        self.records.clear()
        self.editor.on_load(saved)
        self.assertFalse(self.editor.is_validated()[0])
        with self.assertRaises(ValueError):
            self.editor.deploy_fields()
        saved["channel"] = "payload.send"
        self.editor.on_load(saved)
        self.assertIn("outgoing.command", self.editor.is_validated()[1])


if __name__ == "__main__":
    unittest.main()
