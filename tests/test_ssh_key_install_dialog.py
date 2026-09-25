"""Exercise SSH onboarding authentication without contacting a server or Vault."""

from copy import deepcopy
import io
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    import paramiko
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "Phoenix GUI dependencies not installed")
class SSHKeyInstallDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from matrix_gui.registry import ssh_key_install_dialog

        cls.module = ssh_key_install_dialog
        cls.app = QApplication.instance() or QApplication([])
        cls.old_key = paramiko.RSAKey.generate(1024)
        cls.new_key = paramiko.RSAKey.generate(1024)
        old_buffer, new_buffer = io.StringIO(), io.StringIO()
        cls.old_key.write_private_key(old_buffer, password="test-key-passphrase")
        cls.new_key.write_private_key(new_buffer, password="new-key-passphrase")
        cls.old_private = old_buffer.getvalue()
        cls.new_private = new_buffer.getvalue()

    def setUp(self):
        self.serial = "test-ssh-profile"
        self.profile = {
            "serial": self.serial,
            "label": "Test server",
            "host": "server.example.invalid",
            "port": 22,
            "username": "test-user",
            "auth_type": "private_key",
            "password": "stale-password",
            "private_key": self.old_private,
            "private_key_passphrase": "test-key-passphrase",
            "trusted_host_fingerprint": "SHA256:test-pin",
        }
        self.namespace = {self.serial: deepcopy(self.profile)}
        self.store = mock.Mock()
        self.store.get_namespace.return_value = self.namespace
        self.store.commit.return_value = True
        vault = mock.Mock()
        vault.get_store.return_value = self.store

        self.enterContext(mock.patch.object(
            self.module.VaultCoreSingleton, "get", return_value=vault
        ))
        self.enterContext(mock.patch.object(
            self.module, "load_registry_ssh_profiles",
            side_effect=lambda: deepcopy(self.namespace),
        ))
        self.messages = self.enterContext(mock.patch.object(self.module, "QMessageBox"))
        self.dialog = self.module.VaultSSHKeyInstallDialog(
            selected_serial=self.serial
        )
        self.dialog.path_input.setText("test-key-export")
        self.enterContext(mock.patch.object(
            self.dialog, "_confirm_export_replace", return_value=True
        ))
        self.enterContext(mock.patch.object(
            self.dialog, "_verified_fingerprint", return_value="SHA256:test-pin"
        ))
        from matrix_gui.modules.railgun.ssh_support import AuthorizedKeyInstallResult
        self.public_key = self.module.public_key_from_private_key(
            self.old_private, "test-key-passphrase", "phoenix@server.example.invalid"
        )
        self.install_key = self.enterContext(mock.patch.object(
            self.module, "install_authorized_key",
            return_value=AuthorizedKeyInstallResult(False, "/home/test-user/.ssh/authorized_keys")
        ))
        self.export = self.enterContext(mock.patch.object(
            self.module, "save_ssh_key_pair", return_value=("test-key", "test-key.pub")
        ))
        self.install_client = mock.Mock()
        self.verify_client = mock.Mock()
        self.connect = self.enterContext(mock.patch.object(
            self.module, "connect_ssh_profile",
            side_effect=[
                (self.install_client, "SHA256:test-pin"),
                (self.verify_client, "SHA256:test-pin"),
            ],
        ))

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()

    def test_stale_password_cannot_override_selected_key_auth(self):
        self.dialog._install()

        self.assertEqual(2, self.connect.call_count)
        for call in self.connect.call_args_list:
            self.assertEqual("private_key", call.args[0]["auth_type"])
            self.assertEqual(self.old_private, call.args[0]["private_key"])
            self.assertEqual("SHA256:test-pin", call.args[0]["trusted_host_fingerprint"])
        self.install_key.assert_called_once_with(self.install_client, self.public_key)
        self.install_client.close.assert_called_once()
        self.verify_client.close.assert_called_once()
        self.export.assert_called_once()
        self.store.commit.assert_called_once()
        self.assertEqual("stale-password", self.namespace[self.serial]["password"])
        self.messages.critical.assert_not_called()

    def test_selected_method_and_explicit_password_override(self):
        for method, override, expected in (
            ("private_key", "", "private_key"),
            ("password", "", "password"),
            ("agent", "", "agent"),
            ("private_key", "one-time-secret", "password"),
            ("agent", "one-time-secret", "password"),
        ):
            with self.subTest(method=method, override=bool(override)):
                profile = {**self.profile, "auth_type": method}
                before = deepcopy(profile)
                self.dialog.password_input.setText(override)
                candidate = self.dialog._installation_auth_profile(profile, "SHA256:test-pin")
                self.assertEqual(expected, candidate["auth_type"])
                if expected == "password":
                    self.assertEqual(override or "stale-password", candidate["password"])
                else:
                    self.assertNotIn("password", candidate)
                self.assertEqual(before, profile)

    def test_explicit_password_is_not_saved_and_verification_is_key_only(self):
        self.dialog.password_input.setText("one-time-secret")
        self.dialog._install()

        install_config = self.connect.call_args_list[0].args[0]
        verify_config = self.connect.call_args_list[1].args[0]
        self.assertEqual("password", install_config["auth_type"])
        self.assertEqual("one-time-secret", install_config["password"])
        self.assertEqual("private_key", verify_config["auth_type"])
        self.assertEqual("stale-password", self.namespace[self.serial]["password"])
        self.assertEqual("", self.dialog.password_input.text())

    def test_authentication_failure_does_not_retry_with_stored_password(self):
        self.connect.side_effect = paramiko.AuthenticationException("Authentication failed.")
        self.dialog._install()

        self.connect.assert_called_once()
        self.assertEqual("private_key", self.connect.call_args.args[0]["auth_type"])
        self.install_key.assert_not_called()
        self.export.assert_not_called()
        self.store.commit.assert_not_called()
        self.assertEqual(self.profile, self.namespace[self.serial])
        error = self.messages.critical.call_args.args[2]
        self.assertIn("private_key", error)
        self.assertNotIn("stale-password", error)

    def test_verification_failure_retains_password_without_commit(self):
        self.connect.side_effect = [
            (self.install_client, "SHA256:test-pin"),
            paramiko.AuthenticationException("Authentication failed."),
        ]
        self.dialog._install()

        self.install_key.assert_called_once()
        self.install_client.close.assert_called_once()
        self.export.assert_not_called()
        self.store.commit.assert_not_called()
        self.assertEqual(self.profile, self.namespace[self.serial])
        self.assertIn("Verifying private-key login", self.messages.critical.call_args.args[2])

    def test_password_mode_requires_password_and_rejects_unknown_auth(self):
        for changes in (
            {"auth_type": "password", "password": "None"},
            {"auth_type": "unknown"},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.dialog._installation_auth_profile(
                        {**self.profile, **changes}, "SHA256:test-pin"
                    )

    def _use_editor_key(self, **changes):
        self.dialog.key_profile = {
            **self.profile, "serial": "editor-new-profile", "label": "New key",
            "private_key": self.new_private,
            "private_key_passphrase": "new-key-passphrase", **changes,
        }
        self.dialog._refresh_key_preview(self.profile)

    def test_editor_key_is_installed_and_verified_without_changing_login_profile(self):
        self._use_editor_key()
        self.dialog._install()

        self.messages.critical.assert_not_called()
        self.assertEqual(2, self.connect.call_count)
        login = self.connect.call_args_list[0].args[0]
        verify = self.connect.call_args_list[1].args[0]
        self.assertEqual(self.old_private, login["private_key"])
        self.assertEqual(self.new_private, verify["private_key"])
        self.assertEqual("new-key-passphrase", verify["private_key_passphrase"])
        self.assertEqual("private_key", verify["auth_type"])
        self.assertNotIn("password", verify)
        self.assertEqual("SHA256:test-pin", verify["trusted_host_fingerprint"])
        self.assertEqual(
            self.new_key.get_base64(), self.install_key.call_args.args[1].split()[1]
        )
        self.assertEqual(self.new_private.strip(), self.export.call_args.args[1])
        self.store.commit.assert_not_called()
        self.assertEqual(self.profile, self.namespace[self.serial])
        self.assertEqual(self.new_private.strip(), self.dialog.installed_key_profile["private_key"])
        message = self.messages.information.call_args.args[2]
        self.assertIn(self.module.sha256_fingerprint(self.new_key), message)
        self.assertIn("/home/test-user/.ssh/authorized_keys", message)
        self.assertNotIn(self.old_private, message)

    def test_editor_target_mismatches_block_before_probe_or_login(self):
        for changes in (
            {"host": "wrong.example.invalid"}, {"port": 2222},
            {"username": "someone-else"}, {"trusted_host_fingerprint": "SHA256:wrong"},
            {"trusted_host_fingerprint": ""}, {"host": ""}, {"port": 0},
        ):
            with self.subTest(changes=changes):
                self._use_editor_key(**changes)
                self.assertFalse(self.dialog.install_btn.isEnabled())
                self.dialog._install()  # Revalidate even if invoked directly.
                self.dialog._verified_fingerprint.assert_not_called()
                self.connect.assert_not_called()
                self.install_key.assert_not_called()
                self.export.assert_not_called()
                self.store.commit.assert_not_called()

    def test_login_profile_changes_are_revalidated_at_install_time(self):
        self._use_editor_key()
        self.namespace[self.serial]["trusted_host_fingerprint"] = "SHA256:changed"
        self.dialog._install()
        self.connect.assert_not_called()
        self.dialog._verified_fingerprint.assert_not_called()

    def test_missing_login_pin_is_not_silently_trusted(self):
        self._use_editor_key()
        self.namespace[self.serial].pop("trusted_host_fingerprint")
        self.dialog._install()
        self.connect.assert_not_called()
        self.dialog._verified_fingerprint.assert_not_called()

    def test_equivalent_host_case_port_and_pin_padding_are_accepted(self):
        self._use_editor_key(host="SERVER.EXAMPLE.INVALID", port="22",
                             trusted_host_fingerprint="SHA256:test-pin=")
        self.assertTrue(self.dialog.install_btn.isEnabled())
        self.dialog._install()
        self.messages.critical.assert_not_called()
        self.assertEqual(2, self.connect.call_count)

    def test_failed_new_key_verification_does_not_fallback_or_save(self):
        self._use_editor_key()
        self.connect.side_effect = [
            (self.install_client, "SHA256:test-pin"),
            paramiko.AuthenticationException("New key rejected"),
        ]
        self.dialog._install()
        self.assertEqual(2, self.connect.call_count)
        self.assertEqual(self.new_private, self.connect.call_args.args[0]["private_key"])
        self.assertIsNone(self.dialog.installed_key_profile)
        self.assertEqual(self.profile, self.namespace[self.serial])
        self.store.commit.assert_not_called()
        self.export.assert_not_called()

    def test_editor_export_uses_editor_key_not_login_key(self):
        self._use_editor_key()
        self.dialog._save_only()
        self.assertEqual(self.new_private.strip(), self.export.call_args.args[1])
        self.connect.assert_not_called()
        self.store.commit.assert_not_called()

    def test_real_fingerprint_check_blocks_changed_live_host(self):
        with mock.patch.object(self.module, "probe_ssh_host_fingerprint",
                               return_value="SHA256:impostor"):
            with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                self.module.VaultSSHKeyInstallDialog._verified_fingerprint(
                    self.dialog, self.profile
                )
        self.connect.assert_not_called()

    def test_editor_hands_current_unsaved_key_to_dialog(self):
        from matrix_gui.registry.object_classes.editors.ssh import SSH
        editor = SSH()
        try:
            editor.on_load(self.profile)
            editor.private_key.setPlainText(self.new_private)
            editor.passphrase.setText("new-key-passphrase")
            with mock.patch.object(self.module, "VaultSSHKeyInstallDialog") as factory:
                factory.return_value.installed_key_profile = None
                factory.return_value.updated_profile = None
                editor._install_public_key()
                snapshot = factory.call_args.kwargs["key_profile"]
                self.assertEqual(self.new_private.strip(), snapshot["private_key"])
                self.assertEqual("new-key-passphrase", snapshot["private_key_passphrase"])
                self.assertEqual(self.profile["trusted_host_fingerprint"], snapshot["trusted_host_fingerprint"])
        finally:
            editor.close()
            editor.deleteLater()


if __name__ == "__main__":
    unittest.main()
