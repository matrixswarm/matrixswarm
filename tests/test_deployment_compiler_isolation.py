"""Compilation must not mutate saved graph inputs or resolved credentials."""
import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from matrix_gui.swarm_workspace.cls_lib.constraint.constraint_object import Constraint
from matrix_gui.swarm_workspace.cls_lib.deployment.deployment_compiler import DeploymentCompiler
from matrix_gui.swarm_workspace.cls_lib.deployment.directive_compiler import DirectiveCompiler


class CompilerIsolationTests(unittest.TestCase):
    def make_ir(self, mode="one_shot"):
        node = {"connection": {"proto": "ssh"}, "config": {"ssh_mode": mode}}
        fields = {"channel": "outgoing.command", "options": {"nested": ["original"]}}
        constraint = Constraint("ssh", SimpleNamespace(is_connection=lambda: True), {})
        constraint.fields = fields
        ir = SimpleNamespace(node=node, name="matrix_ssh", universal_id="test",
                             children=[], resolved={"ssh": constraint})
        return {"root": ir}, node, fields

    def test_success_does_not_mutate_source_and_output_is_detached(self):
        ir, node, fields = self.make_ir()
        before = deepcopy(node)
        output = DeploymentCompiler(ir, "root").compile()
        self.assertEqual(node, before)
        output["agents"]["connection"]["options"]["nested"].append("changed")
        self.assertEqual(fields["options"]["nested"], ["original"])

    def test_rejected_compile_does_not_mutate_source(self):
        ir, node, fields = self.make_ir("invalid-mode")
        before = deepcopy(node)
        with self.assertRaises(ValueError):
            DeploymentCompiler(ir, "root").compile()
        self.assertEqual(node, before)

    def test_public_fields_detached_and_provider_called_once(self):
        for path in (["config"], ["config", "transport"]):
            for explicit in (True, False):
                with self.subTest(path=path, explicit=explicit):
                    fields = {"nested": ["original"]}
                    provider = Mock(return_value=fields if explicit else {})
                    con = SimpleNamespace(is_deployment_only=lambda: False,
                        fields=fields, handler=SimpleNamespace(
                            directive_fields=provider, get_directory_path=lambda: path))
                    ir = SimpleNamespace(node={"config": {}}, name="test", universal_id="test",
                        children=[], resolved={"test": con})
                    result = DirectiveCompiler({"root": ir}, "root").compile()
                    cfg = result["agents"]["config"]
                    target = cfg["transport"] if len(path) > 1 else cfg
                    target["nested"].append("modified")
                    self.assertEqual(fields, {"nested": ["original"]})
                    provider.assert_called_once_with()

    def test_reused_compiler_does_not_retain_removed_certs(self):
        ir, _, _ = self.make_ir()
        con = Constraint("certificate", SimpleNamespace(is_connection=lambda: False), {})
        con.fields = {"certificate": "synthetic"}
        ir["root"].resolved = {"certificate": con}
        compiler = DeploymentCompiler(ir, "root")
        first = compiler.compile()
        ir["root"].resolved = {}
        second = compiler.compile()
        self.assertEqual(second["certs"], {})
        self.assertEqual(first["certs"], {"test": {"certificate": "synthetic"}})

    def test_failed_compile_discards_partial_certificates(self):
        ir, _, _ = self.make_ir("invalid-mode")
        con = Constraint("certificate", SimpleNamespace(is_connection=lambda: False), {})
        con.fields = {"certificate": "synthetic"}
        ir["root"].resolved = {"certificate": con}
        compiler = DeploymentCompiler(ir, "root")
        with self.assertRaises(ValueError):
            compiler.compile()
        self.assertEqual(compiler.certs, {})

    def test_connection_injection_failure_is_not_reclassified_as_certificate(self):
        ir, node, _ = self.make_ir()
        ir["root"].resolved["ssh"].handler.is_connection = Mock(
            side_effect=RuntimeError("SECRET-MARKER"))
        compiler = DeploymentCompiler(ir, "root")
        with self.assertRaises(ValueError) as error:
            compiler.compile()
        self.assertNotIn("SECRET-MARKER", str(error.exception))
        self.assertEqual(compiler.certs, {})
        self.assertEqual(node["connection"], {"proto": "ssh"})


if __name__ == "__main__":
    unittest.main()
