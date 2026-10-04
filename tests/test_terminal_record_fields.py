"""GUI-only terminal metadata: synthetic records, no endpoints or remote I/O."""
import base64
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from PyQt6.QtWidgets import QApplication
from matrix_gui.core import startup_policy as policy
from matrix_gui.registry import terminal_fields as fields
from matrix_gui.registry.object_classes.editors import matrix_ssh
from matrix_gui.registry.registry_manager import RegistryManagerDialog
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.modules.vault.crypto.vault_handler import save_vault_singlefile, load_vault_singlefile


class TerminalRecordFieldsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        policy.reset_startup_policy()
        self.addCleanup(policy.reset_startup_policy)
        base = dict(label="Synthetic", host="example.invalid", port=22, username="tester", auth_type="password",
                    password="synthetic-only", trusted_host_fingerprint="SHA256:" + "A" * 43)
        self.records = {
            "a" * 32: dict(base, serial="a" * 32, label="Original"),
            "b" * 32: dict(base, serial="b" * 32, username="other"),
            "c" * 32: dict(base, serial="c" * 32, host="other.invalid"),
            "d" * 32: dict(base, serial="d" * 32, port=2222),
            "e" * 32: dict(base, serial="e" * 32, trusted_host_fingerprint="SHA256:" + base64.b64encode(b"\x01" * 32).decode().rstrip("=")),
        }
        self.target = fields.ssh_target(base)
        self.patch = patch.object(matrix_ssh.MatrixSSH, "_ssh_records", return_value=self.records)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def editor(self, visible):
        with patch.object(matrix_ssh, "fields_visible", return_value=visible):
            editor = matrix_ssh.MatrixSSH()
        self.addCleanup(editor.deleteLater)
        return editor

    def select_target(self, editor):
        editor.target_server.setCurrentIndex(editor.target_server.findData(self.target))
        editor.ssh.setCurrentIndex(editor.ssh.findData("a" * 32))

    def test_normal_editor_unchanged_and_terminal_fields_hidden(self):
        editor = self.editor(False)
        self.assertTrue(editor.terminal_group.isHidden())
        self.assertEqual(6, editor.ssh.count())
        editor.ssh.setCurrentIndex(1)
        self.assertTrue(editor.is_validated()[0])
        self.assertNotIn("meta", editor.serialize())

    def test_visible_fields_filter_host_port_and_pin_not_just_label(self):
        editor = self.editor(True)
        self.assertFalse(editor.terminal_group.isHidden())
        self.assertEqual(1, editor.ssh.count())
        self.assertFalse(editor.is_validated()[0])
        self.select_target(editor)
        self.assertEqual([None, "a" * 32, "b" * 32], [editor.ssh.itemData(i) for i in range(editor.ssh.count())])
        self.assertTrue(editor.is_validated()[0])
        editor.target_server.setCurrentIndex(0)
        self.assertIsNone(editor.ssh.currentData())

    def test_metadata_round_trip_and_not_in_deployed_fields(self):
        editor = self.editor(True)
        self.select_target(editor)
        saved = editor.serialize()
        self.assertEqual(self.target, saved["meta"]["terminal"]["target_server"])
        self.assertNotIn("password", saved["meta"]["terminal"])
        other = self.editor(True)
        other.on_load(saved)
        self.assertEqual(saved, other.serialize())
        deployed = other.deploy_fields()
        self.assertNotIn("meta", deployed)
        self.assertNotIn("terminal", deployed)
        self.assertNotIn("target_server", deployed)
        self.assertEqual("outgoing.command", deployed["channel"])

    def test_hidden_metadata_survives_without_becoming_gui_authority(self):
        editor = self.editor(True)
        self.select_target(editor)
        saved = editor.serialize()
        saved["meta"]["terminal"]["future_note"] = "keep me"
        hidden = self.editor(False)
        hidden.on_load(saved)
        hidden.ssh.setCurrentIndex(hidden.ssh.findData("c" * 32))
        self.assertTrue(hidden.is_validated()[0])
        self.assertEqual(saved["meta"], hidden.serialize()["meta"])
        reopened = self.editor(True)
        reopened.on_load(hidden.serialize())
        self.assertFalse(reopened.is_validated()[0])
        with self.assertRaises(ValueError):
            reopened.serialize()

    def test_edited_deleted_or_forged_selection_rechecked_before_save(self):
        editor = self.editor(True)
        self.select_target(editor)
        self.records["a" * 32]["port"] = 2222
        self.assertFalse(editor.is_validated()[0])
        with self.assertRaises(ValueError):
            editor.serialize()
        del self.records["a" * 32]
        self.assertFalse(editor.is_validated()[0])

    def test_unknown_terminal_schema_preserved_when_hidden_and_rejected_when_visible(self):
        record = {"serial": "f" * 32, "label": "Route", "ssh_serial": "a" * 32,
                  "meta": {"terminal": {"schema_version": 9, "target_server": self.target}}}
        hidden = self.editor(False)
        hidden.on_load(record)
        self.assertEqual(record["meta"], hidden.serialize()["meta"])
        visible = self.editor(True)
        visible.on_load(record)
        self.assertIn("Unsupported", visible.is_validated()[1])

    def test_registry_edit_keeps_editor_metadata_and_unrelated_metadata(self):
        record = {"serial": "f" * 32, "label": "Route", "ssh_serial": "a" * 32,
                  "meta": {"created": "keep-date", "unrelated": {"keep": True}}}
        store = SimpleNamespace(get_namespace=lambda name: {"f" * 32: deepcopy(record)})
        commits = []
        manager = SimpleNamespace(registry_store=store, terminal_mode=True,
            _commit_namespace=lambda name, data: commits.append(deepcopy(data)) or True,
            _populate_tabs=Mock(), _stamp_record=RegistryManagerDialog._stamp_record)

        def accept(editor):
            self.select_target(editor)
            return 1

        with patch.object(matrix_ssh, "fields_visible", return_value=True), \
             patch.object(matrix_ssh.MatrixSSH, "exec", accept):
            RegistryManagerDialog._edit_existing(manager, "matrix_ssh", "f" * 32)
        meta = commits[0]["f" * 32]["meta"]
        self.assertEqual("keep-date", meta["created"])
        self.assertEqual({"keep": True}, meta["unrelated"])
        self.assertEqual(self.target, meta["terminal"]["target_server"])
        self.assertNotIn("terminal", record["meta"])

    def test_window_mode_does_not_write_vault_or_remove_encrypted_metadata(self):
        editor = self.editor(True)
        self.select_target(editor)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.json"
            data = {"padding": "x" * 256, "registry": {"ssh": self.records, "matrix_ssh": {"route": editor.serialize()}},
                    "ui_preferences": {"theme": "untouched", "llm_terminal_fields": True}}
            core = VaultCoreSingleton(data, "synthetic-only", path)
            save_vault_singlefile(data, "synthetic-only", str(path))
            original = path.read_bytes()
            before = core.read()
            with patch("matrix_gui.modules.vault.services.vault_core_singleton.EventBus.emit") as emit:
                self.assertFalse(fields.fields_visible(core))
                self.assertTrue(fields.fields_visible(core, terminal_mode=True))
                policy.reset_startup_policy()
                self.assertFalse(fields.fields_visible(core))
                emit.assert_not_called()
            self.assertEqual(before, core.read())
            self.assertEqual(original, path.read_bytes())
            loaded = load_vault_singlefile("synthetic-only", str(path))
            self.assertEqual(data["registry"], loaded["registry"])
            self.assertEqual(data["ui_preferences"], loaded["ui_preferences"])

    def test_display_flag_is_strict_boolean_and_requires_open_vault(self):
        core = VaultCoreSingleton({"padding": "x" * 256}, "", "unused")
        self.assertFalse(fields.fields_visible(core))
        for value in ("true", 1, None):
            self.assertFalse(fields.fields_visible(core, terminal_mode=value))
        self.assertTrue(fields.fields_visible(core, terminal_mode=True))
        with patch.object(VaultCoreSingleton, "get", side_effect=RuntimeError("locked")):
            self.assertFalse(fields.fields_visible(terminal_mode=True))
        core._closed = True
        self.assertFalse(fields.fields_visible(core, terminal_mode=True))

    def test_registry_has_no_mode_switch_and_editors_use_explicit_window_context(self):
        core = VaultCoreSingleton({"padding": "x" * 256}, "", "unused")
        with patch.object(VaultCoreSingleton, "get", return_value=core), \
             patch.object(RegistryManagerDialog, "get_live_constraint_classes", return_value=[]), \
             patch.object(RegistryManagerDialog, "_populate_tabs"):
            manager = RegistryManagerDialog()
            self.addCleanup(manager.deleteLater)
            self.assertFalse(hasattr(manager, "terminal_fields"))
            for enabled in (False, True, True, False):
                editor = matrix_ssh.MatrixSSH(terminal_mode=enabled)
                self.addCleanup(editor.deleteLater)
                self.assertEqual(not enabled, editor.terminal_group.isHidden())

    def test_endpoint_matching_is_canonical_and_never_resolves_dns(self):
        record = deepcopy(self.records["a" * 32])
        record.update(host="EXAMPLE.INVALID.", port="22")
        record["trusted_host_fingerprint"] += "="
        with patch("socket.getaddrinfo", side_effect=AssertionError("No DNS in an editor")):
            self.assertEqual(self.target, fields.ssh_target(record))
        for changes in ({"port": True}, {"port": 0}, {"port": 22.1}, {"host": "bad\nhost"},
                        {"trusted_host_fingerprint": "SHA256:invalid"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                fields.ssh_target(dict(record, **changes))
if __name__ == "__main__":
    unittest.main()
