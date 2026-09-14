import io
import sys
import unittest
from pathlib import Path


PHOENIX_ROOT = Path(__file__).resolve().parents[1] / "phoenix"
sys.path.insert(0, str(PHOENIX_ROOT))

try:
    import paramiko
    from matrix_gui.modules.railgun.ssh_support import load_private_key
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


if __name__ == "__main__":
    unittest.main()
