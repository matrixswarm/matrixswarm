from enum import IntEnum
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))

from matrix_gui.modules.vault.crypto.yubikey_factor import (  # noqa: E402
    build_yubikey_challenge,
    derive_vault_password,
    normalize_secondary_word,
    request_yubikey_credential,
)
class YubiKeyVaultFactorTests(unittest.TestCase):
    def test_challenge_is_stable_and_exactly_64_bytes(self):
        first = build_yubikey_challenge("Victory Always")
        second = build_yubikey_challenge("Victory Always")
        self.assertEqual(first, second)
        self.assertEqual(64, len(first))
        self.assertNotEqual(first, build_yubikey_challenge("Victory always"))

    def test_unicode_secondary_word_is_normalized_stably(self):
        self.assertEqual("caf\u00e9", normalize_secondary_word(" cafe\u0301 "))
        self.assertEqual(
            build_yubikey_challenge("caf\u00e9"),
            build_yubikey_challenge("cafe\u0301"),
        )

    def test_response_and_word_produce_full_strength_password(self):
        password = derive_vault_password("Victory Always", b"A" * 20)
        self.assertEqual(43, len(password))
        self.assertRegex(password, re.compile(r"^[A-Za-z0-9_-]{43}$"))
        self.assertNotEqual(
            password,
            derive_vault_password("Victory Always", b"B" * 20),
        )
        self.assertNotEqual(
            password,
            derive_vault_password("Different", b"A" * 20),
        )

    def test_empty_word_and_malformed_response_are_rejected(self):
        with self.assertRaises(ValueError):
            build_yubikey_challenge("   ")
        with self.assertRaises(ValueError):
            derive_vault_password("word", b"too short")

    def test_phoenix_owns_dependency_and_remote_matrixos_does_not(self):
        phoenix_requirements = (ROOT / "phoenix/requirements.txt").read_text(
            encoding="utf-8"
        )
        matrixos_requirements = (ROOT / "matrixos/requirements.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("yubikey-manager==5.9.2", phoenix_requirements)
        self.assertNotIn("yubikey", matrixos_requirements.lower())

    def test_phoenix_never_reconfigures_yubikey_slots(self):
        source = (
            ROOT
            / "phoenix/matrix_gui/modules/vault/crypto/yubikey_factor.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("put_configuration(", source)
        self.assertNotIn("delete_slot(", source)
        self.assertIn("calculate_hmac_sha1(", source)

    def test_sdk_adapter_reads_slot_two_without_provisioning(self):
        observed = {}

        class FakeOtpConnection:
            pass

        class FakeSlot(IntEnum):
            ONE = 1
            TWO = 2

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        class FakeDevice:
            def open_connection(self, connection_type):
                observed["connection_type"] = connection_type
                return FakeConnection()

        class FakeConfigState:
            def is_configured(self, slot):
                observed["configured_slot"] = slot
                return True

        class FakeSession:
            def __init__(self, connection):
                observed["connection"] = connection

            def get_config_state(self):
                return FakeConfigState()

            def calculate_hmac_sha1(
                self,
                slot,
                challenge,
                cancellation_event,
                on_keepalive,
            ):
                observed["calculated_slot"] = slot
                observed["challenge"] = challenge
                return b"R" * 20

        ykman = ModuleType("ykman")
        ykman.__path__ = []
        ykman_device = ModuleType("ykman.device")
        ykman_device.list_all_devices = lambda connection_types: [
            (FakeDevice(), SimpleNamespace(serial=8675309))
        ]
        yubikit = ModuleType("yubikit")
        yubikit.__path__ = []
        yubikit_core = ModuleType("yubikit.core")
        yubikit_core.__path__ = []
        yubikit_otp = ModuleType("yubikit.core.otp")
        yubikit_otp.OtpConnection = FakeOtpConnection
        yubikit_yubiotp = ModuleType("yubikit.yubiotp")
        yubikit_yubiotp.SLOT = FakeSlot
        yubikit_yubiotp.YubiOtpSession = FakeSession

        fake_modules = {
            "ykman": ykman,
            "ykman.device": ykman_device,
            "yubikit": yubikit,
            "yubikit.core": yubikit_core,
            "yubikit.core.otp": yubikit_otp,
            "yubikit.yubiotp": yubikit_yubiotp,
        }
        with patch.dict(sys.modules, fake_modules):
            credential = request_yubikey_credential("secondary")

        self.assertEqual(8675309, credential.serial)
        self.assertEqual(FakeSlot.TWO, observed["configured_slot"])
        self.assertEqual(FakeSlot.TWO, observed["calculated_slot"])
        self.assertEqual(64, len(observed["challenge"]))
        self.assertEqual(
            derive_vault_password("secondary", b"R" * 20),
            credential.password,
        )

    def test_runtime_event_identifies_authentication_method(self):
        service = (
            ROOT / "phoenix/matrix_gui/modules/vault/vault_service.py"
        ).read_text(encoding="utf-8")
        unlock_dialog = (
            ROOT / "phoenix/matrix_gui/modules/vault/vault_unlock_dialog.py"
        ).read_text(encoding="utf-8")

        self.assertIn('auth_method: str = "password"', service)
        self.assertIn("auth_method=auth_method", service)
        self.assertIn(
            'self._attempt_unlock(password, auth_method="yubikey")',
            unlock_dialog,
        )


if __name__ == "__main__":
    unittest.main()
