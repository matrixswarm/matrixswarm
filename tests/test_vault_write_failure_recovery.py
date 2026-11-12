"""Rejected vault writes must not look saved or leak into later writes."""
from copy import deepcopy
import ast
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QInputDialog, QWidget
from matrix_gui.modules.vault.vault_stores.directive_store import DirectiveStore
from matrix_gui.modules.vault.vault_stores.deployment_store import DeploymentStore
from matrix_gui.registry.object_classes.editors.base_editor import BaseEditor
from matrix_gui.modules.directive import directive_manager_dialog as directives_ui
from matrix_gui.modules.net import edit_connection_dialog as connection_ui
from matrix_gui.modules.vault.services.vault_connection_singleton import VaultConnectionSingleton


class Root:
    def __init__(self):
        self.data = {"directives": {"old": {"label": "old", "json": {}}},
                     "deployments": {"dep": {"label": "old", "agents": []}}}
        self.result = False
    def get_section(self, key):
        return self.data.setdefault(key, {})
    def get_store(self, name):
        return None
    def patch(self, key, value):
        if isinstance(self.result, Exception):
            raise self.result
        if self.result:
            self.data[key] = deepcopy(value)
        return self.result


class FakeEditor(BaseEditor):
    def on_load(self, data): pass
    def serialize(self): return {"test": "draft"}
    def is_validated(self): return True, ""


class VaultWriteFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_directive_and_deployment_changes_roll_back_on_failure_and_exception(self):
        for failure in (False, RuntimeError("disk")):
            for kind in ("update_directive", "delete_directive", "update_dep", "delete_dep"):
                with self.subTest(failure=type(failure).__name__, operation=kind):
                    root = Root()
                    root.result = failure
                    before = deepcopy(root.data)
                    store = DirectiveStore(root) if "directive" in kind else DeploymentStore(root)
                    args = {"update_directive": ("old", {"label": "changed"}),
                            "delete_directive": ("old",),
                            "update_dep": ("dep", {"label": "changed"}),
                            "delete_dep": ("dep",)}[kind]
                    if isinstance(failure, Exception):
                        with self.assertRaises(RuntimeError): getattr(store, kind)(*args)
                    else:
                        self.assertFalse(getattr(store, kind)(*args))
                    self.assertEqual(before, root.data)
                    root.result = True
                    self.assertTrue(store.commit())
                    self.assertEqual(before, root.data)

    def test_directive_dialog_reports_failure_without_claiming_success(self):
        root = Root()
        store = DirectiveStore(root)
        facade = SimpleNamespace(get_store=lambda name: store)
        fake = SimpleNamespace(editor=SimpleNamespace(toPlainText=lambda: '{"agents": []}'), refresh_lists=Mock())
        with patch.object(directives_ui.VaultCoreSingleton, "get", return_value=facade), \
             patch.object(QInputDialog, "getText", return_value=("Test", True)), \
             patch.object(QMessageBox, "warning") as warning, \
             patch.object(QMessageBox, "information") as info:
            directives_ui.DirectiveManagerDialog.save_to_vault(fake)
        warning.assert_called_once()
        info.assert_not_called()
        fake.refresh_lists.assert_not_called()
        self.assertEqual(["old"], list(root.data["directives"]))

    def test_registry_editor_stays_open_on_rejection_then_can_cancel(self):
        editor = FakeEditor()
        save = Mock(return_value=False)
        observations = []
        def click_ok():
            dialog = editor.parentWidget()
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
            observations.append(dialog.isVisible())
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel).click()
        QTimer.singleShot(0, click_ok)
        self.assertFalse(editor.exec(on_save=save))
        self.assertEqual([True], observations)
        save.assert_called_once()

    def test_registry_editor_can_retry_without_losing_draft(self):
        editor = FakeEditor()
        save = Mock(side_effect=[False, True])
        def click_twice():
            buttons = editor.parentWidget().findChild(QDialogButtonBox)
            buttons.button(QDialogButtonBox.StandardButton.Ok).click()
            buttons.button(QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(0, click_twice)
        self.assertTrue(editor.exec(on_save=save))
        self.assertEqual(2, save.call_count)

    def test_connection_editor_stays_open_and_retries_failed_save(self):
        class ConnectionEditor(QWidget):
            def __init__(self, parent, **kwargs): super().__init__(parent)
            def on_create(self): pass
            def validate(self): return True, ""
            def serialize(self): return {"serial": "entry", "label": "draft", "proto": "test"}
        provider = SimpleNamespace(get_default_channel_options=lambda: [])
        save = Mock(side_effect=[False, True])
        visible = []
        def click_twice():
            dialog = QApplication.activeModalWidget()
            buttons = dialog.findChild(QDialogButtonBox)
            buttons.button(QDialogButtonBox.StandardButton.Ok).click()
            visible.append(dialog.isVisible())
            buttons.button(QDialogButtonBox.StandardButton.Ok).click()
        with patch.dict(connection_ui.CONNECTION_EDITOR_REGISTRY, {"test": ConnectionEditor}), \
             patch.dict(connection_ui.CONNECTION_PROVIDER_REGISTRY, {"test": provider}):
            QTimer.singleShot(0, click_twice)
            entry_id, data = connection_ui.edit_connection_dialog(None, default_proto="test", new_conn=True, on_save=save)
        self.assertEqual([True], visible)
        self.assertEqual(("entry", "draft"), (entry_id, data["label"]))
        self.assertEqual(2, save.call_count)

    def test_session_vault_updates_require_confirmed_write(self):
        class Pipe:
            def __init__(self, ok): self.ok, self.messages = ok, []
            def send(self, payload):
                self.messages.extend([{"type": "other"}, {"type": "vault.update.response",
                    "dep_id": payload["dep_id"], "request_id": payload["request_id"], "ok": self.ok}])
            def poll(self, timeout): return bool(self.messages)
            def recv(self): return self.messages.pop(0)
        for ok in (False, True):
            with self.subTest(ok=ok):
                vault = VaultConnectionSingleton("deployment", Pipe(ok))
                vault.load({"favorites": ["old"]})
                if ok:
                    self.assertTrue(vault.update_field("favorites", ["new"]))
                else:
                    with self.assertRaises(RuntimeError):
                        vault.update_field("favorites", ["new"])
                self.assertEqual(["new"] if ok else ["old"], vault.read_deployment()["favorites"])
                self.assertEqual([{"type": "other"}], vault.take_deferred_messages())

    def test_cockpit_acknowledges_rejected_session_write(self):
        path = Path(__file__).resolve().parents[1] / "phoenix/phoenix.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PhoenixCockpit")
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_handle_session_msg")
        store = SimpleNamespace(update_dep=lambda dep_id, value: False)
        vault = SimpleNamespace(access_control=SimpleNamespace(ai_mode=False), get_store=lambda name: store)
        namespace = {"VaultCoreSingleton": SimpleNamespace(get=lambda: vault)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
        conn = Mock()
        namespace["_handle_session_msg"](SimpleNamespace(), {"type": "vault.update.requested", "dep_id": "dep",
            "request_id": "request", "patch": {"terminal_favorites": []}}, conn)
        conn.send.assert_called_once_with({"type": "vault.update.response", "dep_id": "dep", "request_id": "request", "ok": False})


if __name__ == "__main__":
    unittest.main()
