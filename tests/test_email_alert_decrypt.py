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


PANEL_PATH = (
    Path(__file__).parents[1]
    / "phoenix/matrix_gui/core/panel/custom_panels/email_send/email_send.py"
)


def load_decrypt_contract():
    """Load only the panel's pure decrypt functions, without importing PyQt."""
    source = PANEL_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
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
                isinstance(target, ast.Name)
                and target.id in {
                    "ENCRYPTED_ALERT_MARKER",
                    "ENCRYPTED_ALERT_HANDLER",
                }
                for target in node.targets
            )
        )
        or (isinstance(node, ast.FunctionDef) and node.name in names)
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


class EmailAlertDecryptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_decrypt_contract()

    def setUp(self):
        self.serial = "a" * 64
        self.clear_payload = {
            "handler": "email_send.alert",
            "content": {
                "subject": "SSH Login Detected",
                "body": "Authenticated alert body",
                "origin": "tripwire-lite",
                "level": "warning",
                "timestamp": 101,
            },
        }
        self.signed = {
            "content": {"cipher": "authenticated"},
            "serial": self.serial,
            "timestamp": 100,
            "expires": 200,
            "hash": hashlib.sha256(
                f"{self.serial}email-send-message".encode("utf-8")
            ).hexdigest(),
            "sig": "valid-signature",
        }

        def verify(payload, signature, key):
            self.assertNotIn("sig", payload)
            self.assertEqual(key[0], "rsa")
            if signature != "valid-signature":
                raise ValueError("invalid signature")

        def decrypt(sealed, private_key):
            self.assertEqual(private_key, "phoenix-private-key")
            if sealed != {"cipher": "authenticated"}:
                raise ValueError("authentication failed")
            return self.clear_payload

        self.contract["verify_signed_payload"] = verify
        self.contract["decrypt_with_ephemeral_aes"] = decrypt

    def encoded_message(self, signed=None, copied_email=False):
        envelope = {"content": signed or self.signed}
        encoded = base64.b64encode(
            json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        if copied_email:
            midpoint = len(encoded) // 2
            return (
                "From: alerts@example.invalid\n"
                "Subject: MatrixSwarm Encrypted Alert\n\n"
                "> MATRIXSWARM-ENCRYPTED-ALERT-V1\n"
                f"> {encoded[:midpoint]}\n"
                f"> {encoded[midpoint:]}\n"
                "> footer"
            )
        return f"MATRIXSWARM-ENCRYPTED-ALERT-V1\n{encoded}"

    def decrypt(self, message=None, now=150):
        return self.contract["decrypt_alert_message"](
            message or self.encoded_message(),
            self.serial,
            "sender-public-key",
            "phoenix-private-key",
            now=now,
        )

    def test_valid_current_alert_is_decrypted(self):
        result = self.decrypt()
        self.assertEqual(result["subject"], "SSH Login Detected")
        self.assertEqual(result["body"], "Authenticated alert body")
        self.assertFalse(result["expired"])

    def test_expired_authenticated_alert_remains_viewable(self):
        result = self.decrypt(now=201)
        self.assertEqual(result["body"], "Authenticated alert body")
        self.assertTrue(result["expired"])

    def test_complete_quoted_email_can_be_pasted(self):
        result = self.decrypt(self.encoded_message(copied_email=True))
        self.assertEqual(result["origin"], "tripwire-lite")

    def test_serial_mismatch_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.contract["decrypt_alert_message"](
                self.encoded_message(),
                "b" * 64,
                "sender-public-key",
                "phoenix-private-key",
            )

    def test_wrong_purpose_hash_fails_closed(self):
        self.signed["hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "purpose hash"):
            self.decrypt()

    def test_invalid_signature_fails_closed(self):
        self.signed["sig"] = "tampered"
        with self.assertRaisesRegex(ValueError, "invalid signature"):
            self.decrypt()

    def test_wrong_inner_handler_fails_closed(self):
        self.clear_payload["handler"] = "something.else"
        with self.assertRaisesRegex(ValueError, "not an email alert"):
            self.decrypt()

    def test_panel_is_self_contained_and_uses_current_agent_certificate(self):
        source = PANEL_PATH.read_text(encoding="utf-8")
        compile(source, str(PANEL_PATH), "exec")
        self.assertIn('self.tabs.addTab(self.decrypt_tab, "🔓 Decrypt Message")', source)
        self.assertIn('fetch_fresh(target="deployment")', source)
        self.assertIn('(self.node or {}).get("universal_id")', source)
        self.assertIn('signing.get("pubkey")', source)
        self.assertIn('signing.get("remote_privkey")', source)
        self.assertNotIn("unwrap_secure_packet", source)
        self.assertNotIn("from .alert_decrypt", source)


if __name__ == "__main__":
    unittest.main()
