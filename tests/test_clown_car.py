"""Offline regression coverage for Clown Car discovery, retry, and sealed deployment."""

import base64
from copy import deepcopy
import hashlib
import importlib
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matrix_gui.core.class_lib.paths.agent_root_selector import (
    AgentRootSelector, AgentSourceSelection,
)
from matrix_gui.modules.vault.crypto.cert_utils import embed_agent_sources, set_hash_bang
from matrix_gui.modules.vault.crypto.deploy_tools import (
    generate_swarm_encrypted_directive, decrypt_swarm_encrypted_directive,
)

try:
    from PyQt6.QtWidgets import QApplication, QDialog
except ImportError:
    QApplication = None


def tree():
    return {"agents": {"name": "matrix", "children": [{"name": "worker", "children": []}]}}


class SourceFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="clown-car-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def source(self, relative, content=b"print('test agent')\n"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path


class ClownCarSourceTests(SourceFixture):
    def test_wrapper_checks_real_agents_instead_of_vacuous_success(self):
        with mock.patch.object(AgentRootSelector, "find_agent_source", wraps=AgentRootSelector.find_agent_source) as lookup:
            missing = AgentRootSelector.verify_all_sources(tree(), str(self.root))
        self.assertEqual(["matrix (python)", "worker (python)"], missing)
        self.assertEqual(2, lookup.call_count)

    def test_bare_node_list_and_wrapped_list(self):
        path = self.source("matrix.py")
        for directive in ({"name": "matrix"}, [{"name": "matrix"}], {"agents": [{"name": "matrix"}]}):
            with self.subTest(directive=directive):
                selection = AgentSourceSelection(directive)
                self.assertTrue(selection.add_directory(self.root))
                selection.apply()
                self.assertEqual(str(path), selection.nodes[0]["src"])

    def test_empty_malformed_and_unsafe_names_fail_closed(self):
        for directive in ({}, [], {"agents": []}, {"agents": None}, {"name": "matrix", "children": {}},
                          {"name": "../matrix"}, {"name": "*"}, {"name": "a/b"},
                          {"name": "matrix", "lang": "unknown"}, {"agents": [{"children": []}]}):
            with self.subTest(directive=directive), self.assertRaises(ValueError):
                AgentSourceSelection(directive)
        cyclic = {"name": "matrix"}
        cyclic["children"] = [cyclic]
        with self.assertRaises(ValueError):
            AgentSourceSelection(cyclic)

    def test_monorepo_matrixos_agents_core_and_package_roots(self):
        path = self.source("matrixos/agents/python_core/matrix/matrix.py")
        for folder in (self.root, self.root / "matrixos", self.root / "matrixos/agents",
                       self.root / "matrixos/agents/python_core", path.parent):
            with self.subTest(folder=folder):
                self.assertEqual(str(path), AgentRootSelector.find_agent_source("matrix", "python", str(folder)))

    def test_all_declared_languages_and_language_core_preference(self):
        shell = self.source("agents/bash_core/worker/worker.sh")
        python = self.source("agents/python_core/worker/worker.py")
        self.assertEqual(str(shell), AgentRootSelector.find_agent_source("worker", "BASH", str(self.root)))
        self.assertEqual(str(python), AgentRootSelector.find_agent_source("worker", "python", str(self.root)))

    def test_package_init_fallback_is_python_only(self):
        path = self.source("worker/__init__.py")
        self.assertEqual(str(path), AgentRootSelector.find_agent_source("worker", "python", str(path.parent)))
        self.assertIsNone(AgentRootSelector.find_agent_source("worker", "go", str(path.parent)))

    def test_duplicate_sources_require_exact_directory(self):
        first = self.source("a/worker/worker.py", b"first\n")
        second = self.source("b/worker/worker.py", b"second\n")
        selection = AgentSourceSelection({"name": "worker"})
        self.assertFalse(selection.add_directory(self.root))
        self.assertIn("Multiple sources", selection.errors[("worker", "python")])
        self.assertTrue(selection.add_directory(second.parent))
        self.assertEqual(str(second), selection.sources[("worker", "python")])
        self.assertNotEqual(str(first), selection.sources[("worker", "python")])

    def test_partial_selection_is_retained_and_shared_by_duplicate_agent_nodes(self):
        matrix = self.source("primary/matrix.py")
        worker = self.source("extra/worker.py")
        self.source("extra/matrix.py", b"do not replace the selected matrix\n")
        directive = tree()
        directive["agents"]["children"].append({"name": "worker"})
        selection = AgentSourceSelection(directive)
        self.assertFalse(selection.add_directory(matrix.parent))
        with self.assertRaises(FileNotFoundError):
            selection.add_directory(self.root / "does-not-exist")
        self.assertEqual(str(matrix), selection.sources[("matrix", "python")])
        self.assertTrue(selection.add_directory(worker.parent))
        selection.apply()
        self.assertEqual(str(matrix), directive["agents"]["src"])
        self.assertTrue(all(node["src"] == str(worker) for node in directive["agents"]["children"]))
        self.assertEqual([str(matrix.parent), str(worker.parent)], selection.roots)

    def test_partial_selection_and_failed_apply_do_not_mutate_directive(self):
        self.source("matrix.py")
        directive = tree()
        before = deepcopy(directive)
        selection = AgentSourceSelection(directive)
        selection.add_directory(self.root)
        with self.assertRaisesRegex(ValueError, "worker"):
            selection.apply()
        self.assertEqual(before, directive)

    def test_disappeared_source_becomes_missing_again(self):
        path = self.source("matrix.py")
        selection = AgentSourceSelection({"name": "matrix"})
        self.assertTrue(selection.add_directory(self.root))
        path.unlink()
        selection.refresh()
        self.assertEqual(["matrix (python)"], selection.missing_agents)
        self.assertEqual([], selection.roots)

    def test_unreadable_source_never_counts_as_verified(self):
        self.source("matrix.py")
        selection = AgentSourceSelection({"name": "matrix"})
        with mock.patch.object(selection, "_check_readable", side_effect=PermissionError("denied")):
            self.assertFalse(selection.add_directory(self.root))
        self.assertIn("denied", selection.errors[("matrix", "python")])

    def test_embedding_is_atomic_when_later_source_is_missing(self):
        self.source("matrix.py")
        directive = tree()
        before = deepcopy(directive)
        with self.assertRaisesRegex(ValueError, "worker"):
            embed_agent_sources(directive, self.root)
        self.assertEqual(before, directive)

    def test_embedding_is_atomic_when_later_source_read_fails(self):
        self.source("matrix.py")
        self.source("worker.py")
        directive = tree()
        before = deepcopy(directive)
        with mock.patch.object(Path, "read_bytes", side_effect=[b"matrix\n", PermissionError("denied")]):
            with self.assertRaisesRegex(ValueError, "worker"):
                embed_agent_sources(directive, self.root)
        self.assertEqual(before, directive)

    def test_stale_embedded_code_is_not_a_substitute_for_missing_verified_file(self):
        directive = {"name": "matrix", "src": str(self.root / "deleted.py"),
                     "src_embed": base64.b64encode(b"stale\n").decode()}
        before = deepcopy(directive)
        with self.assertRaisesRegex(ValueError, "Missing source"):
            embed_agent_sources(directive, self.root)
        self.assertEqual(before, directive)

    def test_multiple_roots_embed_and_hash_exact_bytes_through_encryption(self):
        first = b"# matrix\nprint('a')\n"
        second = b"# worker\nprint('b')\n"
        matrix = self.source("main/matrix.py", first)
        worker = self.source("custom/worker.py", second)
        directive = tree()
        selection = AgentSourceSelection(directive)
        selection.add_directory(matrix.parent)
        selection.add_directory(worker.parent)
        selection.apply()
        bundle, key, digest = generate_swarm_encrypted_directive(directive["agents"], base_path=str(matrix.parent))
        decoded = decrypt_swarm_encrypted_directive(bundle, base64.b64encode(key).decode())
        for node, expected in ((decoded, first), (decoded["children"][0], second)):
            self.assertEqual(expected, base64.b64decode(node["src_embed"]))
            self.assertEqual(hashlib.sha256(expected).hexdigest(), node["hash_bang"])
        self.assertEqual(directive["agents"], decoded)
        self.assertEqual(64, len(digest))

    def test_hashing_wrapped_list_and_invalid_base64(self):
        data = b"matrix\n"
        self.source("matrix.py", data)
        directive = {"agents": [{"name": "matrix"}]}
        set_hash_bang(directive, self.root)
        self.assertEqual(hashlib.sha256(data).hexdigest(), directive["agents"][0]["hash_bang"])
        directive = {"name": "matrix", "src_embed": "not base64!"}
        with self.assertRaisesRegex(ValueError, "Invalid embedded source"):
            set_hash_bang(directive)


class FakeVault:
    def __init__(self, data=None):
        self.data = deepcopy(data or {})
        self.writes = []

    def patch(self, key, value):
        self.data[key] = deepcopy(value)
        self.writes.append(key)
        return True

    def get_store(self, name):
        return SimpleNamespace(get_namespace=lambda namespace: {})


@unittest.skipIf(QApplication is None, "Phoenix GUI dependencies not installed")
class ClownCarGuiTests(SourceFixture):
    @classmethod
    def setUpClass(cls):
        cls.validator_module = importlib.import_module("matrix_gui.swarm_workspace.cls_lib.deployment.agent_root_validator")
        cls.dialog_module = importlib.import_module("matrix_gui.core.dialog.agent_root_check_dialog")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        self.vault = FakeVault()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(self.validator_module.VaultCoreSingleton, "get", return_value=self.vault).start()
        self.critical = mock.patch.object(self.validator_module.QMessageBox, "critical").start()
        self.warning = mock.patch.object(self.validator_module.QMessageBox, "warning").start()

    def validator(self, directive, paths):
        return self.validator_module.AgentRootValidator(directive, [str(path) for path in paths])

    def test_complete_cached_root_needs_no_dialog(self):
        self.source("matrix.py")
        self.source("worker.py")
        directive = tree()
        with mock.patch.object(self.validator_module, "AgentRootCheckDialog") as dialog:
            self.assertEqual(str(self.root), self.validator(directive, [self.root]).run())
        dialog.assert_not_called()
        self.assertEqual(str(self.root), self.vault.data["last_agent_path"])
        self.assertTrue(all("src" in node for node in AgentRootSelector.agent_nodes(directive)))

    def test_cached_roots_are_combined_before_prompting(self):
        matrix = self.source("main/matrix.py")
        worker = self.source("custom/worker.py")
        with mock.patch.object(self.validator_module, "AgentRootCheckDialog") as dialog:
            result = self.validator(tree(), [self.root / "gone", matrix.parent, worker.parent]).run()
        self.assertEqual(str(matrix.parent), result)
        dialog.assert_not_called()
        self.assertEqual([str(matrix.parent), str(worker.parent)], self.vault.data["agent_roots"])

    def test_wrong_existing_root_prompts_and_cancel_never_caches_or_mutates(self):
        directive = tree()
        before = deepcopy(directive)
        with mock.patch.object(self.validator_module, "AgentRootCheckDialog") as dialog:
            dialog.return_value.exec_check.return_value = None
            self.assertIsNone(self.validator(directive, [self.root]).run())
        dialog.assert_called_once()
        self.assertEqual([], self.vault.writes)
        self.assertEqual(before, directive)

    def test_partial_cached_sources_survive_selection_of_missing_agent(self):
        matrix = self.source("main/matrix.py")
        worker = self.source("custom/worker.py")

        def make_dialog(directive, parent, *, selection, initial_path):
            self.assertEqual({("matrix", "python"): str(matrix)}, selection.sources)
            self.assertEqual(["worker (python)"], selection.missing_agents)

            def choose():
                selection.add_directory(worker.parent)
                return str(worker.parent)
            return SimpleNamespace(exec_check=choose)

        directive = tree()
        with mock.patch.object(self.validator_module, "AgentRootCheckDialog", side_effect=make_dialog):
            self.assertEqual(str(matrix.parent), self.validator(directive, [matrix.parent]).run())
        self.assertEqual(str(worker), directive["agents"]["children"][0]["src"])
        self.assertEqual([str(matrix.parent), str(worker.parent)], self.vault.data["agent_roots"])

    def test_source_disappearing_after_dialog_acceptance_reopens_selection(self):
        matrix = self.source("main/matrix.py")
        worker = self.source("old/worker.py")
        replacement = self.source("new/worker.py")
        selections = []

        def make_dialog(directive, parent, *, selection, initial_path):
            selections.append(selection)

            def choose():
                if len(selections) == 1:
                    selection.add_directory(worker.parent)
                    worker.unlink()
                    return str(worker.parent)
                selection.add_directory(replacement.parent)
                return str(replacement.parent)
            return SimpleNamespace(exec_check=choose)

        directive = tree()
        with mock.patch.object(self.validator_module, "AgentRootCheckDialog", side_effect=make_dialog):
            self.assertEqual(str(matrix.parent), self.validator(directive, [matrix.parent]).run())
        self.assertEqual(2, len(selections))
        self.assertIs(selections[0], selections[1])
        self.assertEqual(str(replacement), directive["agents"]["children"][0]["src"])

    def test_real_dialog_keeps_retrying_bad_and_partial_directories(self):
        matrix = self.source("main/matrix.py")
        worker = self.source("custom/worker.py")
        empty = self.root / "empty"
        empty.mkdir()
        directive = tree()
        before = deepcopy(directive)
        dialog = self.dialog_module.AgentRootCheckDialog(directive)
        self.addCleanup(dialog.deleteLater)
        choices = [str(self.root / "gone"), str(empty), str(matrix.parent), "", str(worker.parent)]
        with mock.patch.object(self.dialog_module.QFileDialog, "getExistingDirectory", side_effect=choices):
            for expected_count in (0, 0, 1, 1):
                dialog.pick_button.click()
                self.assertEqual(expected_count, len(dialog.selection.sources))
                self.assertEqual(QDialog.DialogCode.Rejected, dialog.result())
            self.assertIn("worker (python)", dialog.editor.toPlainText())
            dialog.pick_button.click()
        self.assertEqual(QDialog.DialogCode.Accepted, dialog.result())
        self.assertEqual(2, len(dialog.selection.sources))
        self.assertEqual(before, directive)  # Applying paths belongs to the validator.

    def test_dialog_cancel_does_not_apply_partial_sources(self):
        self.source("matrix.py")
        directive = tree()
        before = deepcopy(directive)
        dialog = self.dialog_module.AgentRootCheckDialog(directive)
        self.addCleanup(dialog.deleteLater)
        with mock.patch.object(self.dialog_module.QFileDialog, "getExistingDirectory", return_value=str(self.root)):
            dialog.pick_button.click()
        dialog.reject()
        with mock.patch.object(dialog, "exec", return_value=QDialog.DialogCode.Rejected):
            self.assertIsNone(dialog.exec_check())
        self.assertEqual(before, directive)

    def test_empty_tree_never_reaches_directory_selection_or_vault_write(self):
        with mock.patch.object(self.validator_module, "AgentRootCheckDialog") as dialog:
            self.assertIsNone(self.validator({"agents": []}, [self.root]).run())
        dialog.assert_not_called()
        self.critical.assert_called_once()
        self.assertEqual([], self.vault.writes)

    def deploy(self, directive, *, enabled=True):
        module = importlib.import_module("matrix_gui.swarm_workspace.cls_lib.deployment.deploy")
        opts = {"clown_car": enabled, "universe": "test", "linux_user": "matrix-test",
                "railgun_target": {"serial": "test-profile"}}
        mock.patch.object(module.QInputDialog, "getText", return_value=("test", True)).start()
        options = mock.patch.object(module, "DeployOptionsDialog").start()
        options.return_value.exec.return_value = QDialog.DialogCode.Accepted
        options.return_value.get_options.return_value = opts
        preview = mock.patch.object(module, "EncryptionStagingDialog").start()
        preview.return_value.exec.return_value = QDialog.DialogCode.Accepted
        launch = mock.patch.object(module.RailgunDialog, "launch").start()
        generate = mock.patch.object(module, "generate_swarm_encrypted_directive",
                                     wraps=generate_swarm_encrypted_directive).start()
        validator = mock.patch.object(module, "AgentRootValidator",
                                      wraps=self.validator_module.AgentRootValidator).start()
        module.Deploy().deploy_directive(
            None, directive, SimpleNamespace(deployment={"agents": [], "certs": {}}), "workspace-test",
        )
        return SimpleNamespace(launch=launch, generate=generate, validator=validator, preview=preview)

    def test_full_deployment_embeds_multiple_cached_roots_in_sealed_bundle(self):
        matrix = self.source("main/matrix.py", b"matrix bytes\n")
        worker = self.source("custom/worker.py", b"worker bytes\n")
        self.vault.data.update(last_agent_path=str(matrix.parent), agent_roots=[str(worker.parent)])
        directive = tree()
        result = self.deploy(directive)
        self.critical.assert_not_called()
        self.assertIs(directive["agents"], result.validator.call_args.args[0])
        result.launch.assert_called_once()
        record, = self.vault.data["deployments"].values()
        decoded = decrypt_swarm_encrypted_directive(record["encrypted_bundle"], record["swarm_key"])
        self.assertEqual(b"matrix bytes\n", base64.b64decode(decoded["src_embed"]))
        self.assertEqual(b"worker bytes\n", base64.b64decode(decoded["children"][0]["src_embed"]))
        self.assertEqual(hashlib.sha256(b"worker bytes\n").hexdigest(), decoded["children"][0]["hash_bang"])

    def test_full_deployment_cancel_never_encrypts_previews_or_launches(self):
        self.vault.data["last_agent_path"] = str(self.root / "old-location")
        directive = tree()
        before = deepcopy(directive)
        with mock.patch.object(self.validator_module, "AgentRootCheckDialog") as dialog:
            dialog.return_value.exec_check.return_value = None
            result = self.deploy(directive)
        result.generate.assert_not_called()
        result.preview.assert_not_called()
        result.launch.assert_not_called()
        self.assertEqual(before, directive)
        self.assertEqual([], self.vault.writes)

    def test_clown_car_disabled_does_not_discover_or_embed_sources(self):
        result = self.deploy(tree(), enabled=False)
        result.validator.assert_not_called()
        self.critical.assert_not_called()
        result.launch.assert_called_once()
        record, = self.vault.data["deployments"].values()
        decoded = decrypt_swarm_encrypted_directive(record["encrypted_bundle"], record["swarm_key"])
        self.assertNotIn("src_embed", decoded)
        self.assertNotIn("hash_bang", decoded)


if __name__ == "__main__":
    unittest.main()
