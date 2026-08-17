import ast
import base64
import binascii
import hashlib
import hmac
import json
import re
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = (
    ROOT
    / "phoenix/matrix_gui/core/panel/custom_panels/discord_relay/discord_relay.py"
)


def load_decrypt_contract():
    """Load only pure decrypt functions so tests do not require PyQt."""
    source = PANEL_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    constants = {
        "ENCRYPTED_ALERT_MARKER",
        "ENCRYPTED_ALERT_HANDLER",
        "DISCORD_ALERT_HASH_SUFFIX",
    }
    functions = {
        "decode_alert_envelope",
        "_optional_timestamp",
        "decrypt_alert_message",
        "format_alert_timestamp",
    }
    body = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in constants
                for target in node.targets
            )
        )
        or (isinstance(node, ast.FunctionDef) and node.name in functions)
    ]
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "base64": base64,
        "binascii": binascii,
        "hashlib": hashlib,
        "hmac": hmac,
        "json": json,
        "re": re,
        "time": time,
        "datetime": datetime,
        "RSA": SimpleNamespace(import_key=lambda value: ("rsa", value)),
    }
    exec(compile(module, str(PANEL_PATH), "exec"), namespace)
    return namespace


class DiscordAlertDecryptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_decrypt_contract()

    def setUp(self):
        self.serial = "d" * 64
        self.clear_payload = {
            "handler": "discord_relay.alert",
            "content": {
                "message": "Apache crashed on web-01",
                "origin": "apache-watchdog",
                "level": "critical",
                "timestamp": 101,
            },
        }
        self.signed = {
            "content": {"cipher": "authenticated"},
            "serial": self.serial,
            "timestamp": 100,
            "expires": 200,
            "hash": hashlib.sha256(
                f"{self.serial}discord-relay-message".encode("utf-8")
            ).hexdigest(),
            "sig": "valid-signature",
        }

        def verify(payload, signature, key):
            self.assertNotIn("sig", payload)
            self.assertEqual("rsa", key[0])
            if signature != "valid-signature":
                raise ValueError("invalid signature")

        def decrypt(sealed, private_key):
            self.assertEqual("phoenix-private-key", private_key)
            self.assertEqual({"cipher": "authenticated"}, sealed)
            return self.clear_payload

        self.contract["verify_signed_payload"] = verify
        self.contract["decrypt_with_ephemeral_aes"] = decrypt

    def encoded_message(self, signed=None, copied=False):
        envelope = {"content": self.signed if signed is None else signed}
        encoded = base64.b64encode(
            json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        if copied:
            midpoint = len(encoded) // 2
            return (
                "Copied from Discord\n"
                "MATRIXSWARM-ENCRYPTED-ALERT-V1\n"
                "```\n"
                f"{encoded[:midpoint]}\n{encoded[midpoint:]}\n"
                "```\n"
                "Discord footer"
            )
        return f"MATRIXSWARM-ENCRYPTED-ALERT-V1\n{encoded}"

    def decrypt(self, message=None, trusted_serial=None, now=150):
        return self.contract["decrypt_alert_message"](
            message or self.encoded_message(),
            trusted_serial or self.serial,
            "sender-public-key",
            "phoenix-private-key",
            now=now,
        )

    def test_valid_alert_verifies_and_decrypts(self):
        result = self.decrypt()
        self.assertEqual("Apache crashed on web-01", result["message"])
        self.assertEqual("apache-watchdog", result["origin"])
        self.assertFalse(result["expired"])

    def test_expired_authenticated_alert_remains_viewable(self):
        result = self.decrypt(now=201)
        self.assertTrue(result["expired"])

    def test_wrapped_discord_copy_is_accepted(self):
        result = self.decrypt(self.encoded_message(copied=True))
        self.assertEqual("critical", result["level"])

    def test_serial_mismatch_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.decrypt(trusted_serial="b" * 64)

    def test_wrong_purpose_hash_fails_closed(self):
        message = self.encoded_message(dict(self.signed, hash="0" * 64))
        with self.assertRaisesRegex(ValueError, "purpose hash"):
            self.decrypt(message)

    def test_invalid_signature_fails_closed(self):
        message = self.encoded_message(dict(self.signed, sig="tampered"))
        with self.assertRaisesRegex(ValueError, "invalid signature"):
            self.decrypt(message)

    def test_wrong_inner_handler_fails_closed(self):
        self.clear_payload["handler"] = "telegram_relay.alert"
        with self.assertRaisesRegex(ValueError, "not a Discord relay alert"):
            self.decrypt()

    def test_panel_is_decryption_only_and_loader_compatible(self):
        source = PANEL_PATH.read_text(encoding="utf-8")
        self.assertIn("class DiscordRelay(PhoenixPanelInterface)", source)
        self.assertIn('signing.get("pubkey")', source)
        self.assertIn('signing.get("remote_privkey")', source)
        self.assertIn('"DiscordRelay"', source)
        self.assertNotIn("unwrap_secure_packet", source)
        self.assertNotIn("cmd_service_request", source)


if __name__ == "__main__":
    unittest.main()