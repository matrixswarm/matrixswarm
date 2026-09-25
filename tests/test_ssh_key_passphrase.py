import io
import os
import stat
import string
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PHOENIX_ROOT = Path(__file__).resolve().parents[1] / "phoenix"
sys.path.insert(0, str(PHOENIX_ROOT))

try:
    import paramiko
    from matrix_gui.modules.railgun.ssh_support import (
        install_authorized_key,
        connect_ssh_profile,
        generate_strong_passphrase,
        load_private_key,
        public_key_from_private_key,
        save_ssh_key_pair,
        sha256_fingerprint,
        _authorized_key_identity,
    )
except ImportError:
    paramiko = None
    load_private_key = None


@unittest.skipUnless(paramiko is not None, "Paramiko is not installed")
class SSHKeyPassphraseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = paramiko.RSAKey.generate(1024)

    def _serialize(self, password=None):
        output = io.StringIO()
        self.key.write_private_key(output, password=password)
        return output.getvalue()

    def test_arbitrary_passphrase_does_not_validate_unencrypted_key(self):
        with self.assertRaisesRegex(ValueError, "not encrypted"):
            load_private_key(self._serialize(), "anything")

    def test_encrypted_key_requires_its_exact_passphrase(self):
        encrypted = self._serialize("correct horse battery staple")
        loaded = load_private_key(encrypted, "correct horse battery staple")
        self.assertEqual(self.key.get_base64(), loaded.get_base64())
        with self.assertRaises(ValueError):
            load_private_key(encrypted, "wrong")

    def test_public_key_is_derived_from_private_key(self):
        private = self._serialize("correct")
        public = public_key_from_private_key(
            private, "correct", "phoenix test host"
        )
        self.assertEqual(public.split()[:2], [self.key.get_name(), self.key.get_base64()])
        self.assertTrue(public.endswith("phoenix_test_host"))

    def test_generated_passphrase_is_strong_and_whitespace_free(self):
        first = generate_strong_passphrase()
        second = generate_strong_passphrase()
        self.assertEqual(len(first), 48)
        self.assertNotEqual(first, second)
        self.assertFalse(any(character.isspace() for character in first))
        self.assertTrue(any(character in string.ascii_lowercase for character in first))
        self.assertTrue(any(character in string.ascii_uppercase for character in first))
        self.assertTrue(any(character in string.digits for character in first))
        self.assertTrue(any(character in string.punctuation for character in first))

    def test_key_pair_is_exported_atomically(self):
        private = self._serialize("correct")
        public = public_key_from_private_key(private, "correct")
        with tempfile.TemporaryDirectory() as temp, mock.patch(
            "matrix_gui.modules.railgun.ssh_support._harden_private_key_file"
        ):
            target = Path(temp) / "matrix_key"
            private_path, public_path = save_ssh_key_pair(target, private, public)
            self.assertEqual(Path(private_path).read_text().strip(), private.strip())
            self.assertEqual(Path(public_path).read_text().strip(), public)
            self.assertEqual(
                load_private_key(Path(private_path).read_text(), "correct").get_base64(),
                self.key.get_base64(),
            )
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_registry_editor_exposes_organized_key_onboarding(self):
        editor = (
            PHOENIX_ROOT
            / "matrix_gui/registry/object_classes/editors/ssh.py"
        ).read_text(encoding="utf-8")
        for marker in (
            "QTabWidget",
            'QGroupBox("Registry Identity")',
            'QGroupBox("Server & Host Trust")',
            'QGroupBox("Authentication")',
            'QGroupBox("Key Pair")',
            "Save Key Pair to Disk",
            "Install Public Key on Server",
            "Generate Strong Passphrase",
            "VaultSSHKeyInstallDialog",
        ):
            self.assertIn(marker, editor)

        installer = (
            PHOENIX_ROOT
            / "matrix_gui/registry/ssh_key_install_dialog.py"
        ).read_text(encoding="utf-8")
        for marker in (
            "load_registry_ssh_profiles",
            "Save Private + Public Keys",
            "Install && Verify Public Key",
            "Verify && Remove Vault Password",
            "One-Time Password",
            "install_authorized_key",
            'updated["password"] = "None"',
            "registry_store.commit()",
        ):
            self.assertIn(marker, installer)
        self.assertIn(
            'updated["password"] = "None"',
            installer[installer.index("def _remove_password"):],
        )
        install_body = installer[
            installer.index("def _install(self)"):
            installer.index("def _remove_password")
        ]
        self.assertNotIn('updated["password"] = "None"', install_body)

    def test_authorized_key_install_is_idempotent_and_restricts_modes(self):
        private = self._serialize("correct")
        public = public_key_from_private_key(private, "correct")

        class Attr:
            def __init__(self, mode, size=0):
                self.st_mode = mode
                self.st_size = size

        class Writable(io.BytesIO):
            def __init__(self, sftp, path, initial):
                super().__init__(initial)
                self.sftp = sftp
                self.path = path
                self.seek(0, io.SEEK_END)

            def close(self):
                if not self.closed:
                    self.sftp.files[self.path] = self.getvalue()
                super().close()

        class SFTP:
            def __init__(self):
                self.dirs = {"/home/matrix"}
                self.files = {}
                self.modes = {}

            def normalize(self, _path):
                return "/home/matrix"

            def lstat(self, path):
                if path in self.dirs:
                    return Attr(stat.S_IFDIR | 0o700)
                if path in self.files:
                    return Attr(stat.S_IFREG | 0o600, len(self.files[path]))
                raise FileNotFoundError(2, "missing", path)

            def mkdir(self, path, mode):
                self.dirs.add(path)
                self.modes[path] = mode

            def chmod(self, path, mode):
                self.modes[path] = mode

            def open(self, path, mode):
                if mode == "rb":
                    return io.BytesIO(self.files[path])
                if mode == "ab":
                    return Writable(self, path, self.files.get(path, b""))
                raise AssertionError(mode)

            def close(self):
                pass

        sftp = SFTP()
        client = mock.Mock()
        client.open_sftp.return_value = sftp

        first = install_authorized_key(client, public)
        second = install_authorized_key(client, public)
        self.assertTrue(first.installed)
        self.assertFalse(second.installed)
        self.assertEqual(first.remote_path, "/home/matrix/.ssh/authorized_keys")
        self.assertEqual(first.remote_path, second.remote_path)
        authorized = "/home/matrix/.ssh/authorized_keys"
        self.assertEqual(sftp.files[authorized].decode().count(public), 1)
        self.assertEqual(sftp.modes["/home/matrix/.ssh"], 0o700)
        self.assertEqual(sftp.modes[authorized], 0o600)

    def test_authorized_key_options_do_not_cause_duplicate_install(self):
        private = self._serialize("correct")
        public = public_key_from_private_key(private, "correct")
        key_type, payload = public.split()[:2]

        class Attr:
            def __init__(self, mode, size=0):
                self.st_mode = mode
                self.st_size = size

        class SFTP:
            def __init__(self):
                self.path = "/home/matrix/.ssh/authorized_keys"
                self.content = (
                    f'from="192.0.2.10",no-pty {key_type} {payload} existing\n'
                ).encode()

            def normalize(self, _path):
                return "/home/matrix"

            def lstat(self, path):
                if path == "/home/matrix/.ssh":
                    return Attr(stat.S_IFDIR | 0o700)
                if path == self.path:
                    return Attr(stat.S_IFREG | 0o600, len(self.content))
                raise FileNotFoundError(2, "missing", path)

            def chmod(self, _path, _mode):
                pass

            def open(self, path, mode):
                self.assert_path = path
                if mode == "rb":
                    return io.BytesIO(self.content)
                raise AssertionError("Duplicate key should not be appended")

            def close(self):
                pass

        client = mock.Mock()
        client.open_sftp.return_value = SFTP()
        self.assertFalse(install_authorized_key(client, public).installed)

    def test_key_text_in_options_or_comments_is_not_a_duplicate(self):
        identity = (self.key.get_name(), self.key.get_base64())
        fake_key = " ".join(identity)
        other_key = paramiko.RSAKey.generate(1024)
        real_identity = (other_key.get_name(), other_key.get_base64())
        line = f'command="echo {fake_key} extra",no-pty {" ".join(real_identity)} comment'
        self.assertEqual(real_identity, _authorized_key_identity(line))
        self.assertNotEqual(identity, _authorized_key_identity(f"garbage comment {fake_key}"))
        self.assertEqual(identity, _authorized_key_identity(f"{fake_key} unmatched'comment"))

    def test_install_rejects_missing_key_after_write(self):
        public = public_key_from_private_key(self._serialize())
        client = mock.Mock()
        sftp = client.open_sftp.return_value
        sftp.normalize.return_value = "/home/matrix"
        sftp.lstat.side_effect = [
            mock.Mock(st_mode=stat.S_IFDIR | 0o700),
            FileNotFoundError(2, "missing"),
        ]
        sftp.open.side_effect = [io.BytesIO(), io.BytesIO(b"")]
        with self.assertRaisesRegex(RuntimeError, "not found.*after writing"):
            install_authorized_key(client, public)
        sftp.close.assert_called_once()

    def test_private_key_verification_disables_other_authentication(self):
        config = {
            "host": "test.example.invalid", "username": "test-user",
            "auth_type": "private_key", "private_key": self._serialize("correct"),
            "private_key_passphrase": "correct", "password": "must-not-be-used",
            "trusted_host_fingerprint": sha256_fingerprint(self.key),
        }
        with mock.patch("matrix_gui.modules.railgun.ssh_support.paramiko.SSHClient") as factory:
            client = factory.return_value
            client.get_transport.return_value.get_remote_server_key.return_value = self.key
            connect_ssh_profile(config)
            arguments = client.connect.call_args.kwargs
            self.assertEqual(self.key.get_base64(), arguments["pkey"].get_base64())
            self.assertFalse(arguments["allow_agent"])
            self.assertFalse(arguments["look_for_keys"])
            self.assertNotIn("password", arguments)


if __name__ == "__main__":
    unittest.main()
