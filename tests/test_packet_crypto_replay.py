import sys
import base64
import json
import time
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from Crypto.PublicKey import RSA


ROOT = Path(__file__).resolve().parents[1]
MATRIXOS = ROOT / "matrixos"
if str(MATRIXOS) not in sys.path:
    sys.path.insert(0, str(MATRIXOS))
sys.path.insert(0, str(ROOT / "phoenix"))

from core.python_core.class_lib.packet_delivery.utility.encryption import packet_crypto_mixin as replay_module
from core.python_core.class_lib.packet_delivery.utility.encryption.packet_crypto_mixin import PacketCryptoMixin
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.sig_payload_json import SigPayloadJson
from matrix_gui.core.class_lib.packet_delivery.utility.encryption import packet_crypto_mixin as gui_crypto


class _ReceiveFootball:
    def __init__(self, matrix_public_key):
        self.matrix_public_key = matrix_public_key

    def get_allowed_sender_ids(self):
        return {"sender-1"}

    def use_symmetric_encryption(self):
        return False

    def verify_signed_payload(self):
        return True

    def get_pubkey_verifier(self):
        return self.matrix_public_key

    def use_asymmetric_encryption(self):
        return False


class PacketCryptoReplayTests(unittest.TestCase):
    @staticmethod
    def _signed_packet(timestamp=None, payload=None):
        matrix_key = RSA.generate(2048)
        sender_key = RSA.generate(2048)
        timestamp = int(time.time()) if timestamp is None else timestamp
        identity = {
            "universal_id": "sender-1",
            "pub": sender_key.publickey().export_key().decode("utf-8"),
            "timestamp": timestamp,
        }
        signer = PacketCryptoMixin()
        signer.set_logger(lambda *args, **kwargs: None)

        identity_payload = SigPayloadJson()
        identity_payload.set_payload(identity)
        identity_sig = signer.sign_payload(identity_payload, matrix_key)

        subpacket = {
            "identity": {"identity": identity, "sig": identity_sig},
            "payload": {"command": "status"} if payload is None else payload,
            "timestamp": timestamp,
        }
        signed_payload = SigPayloadJson()
        signed_payload.set_payload(subpacket)
        sender_sig = signer.sign_payload(signed_payload, sender_key)
        return (
            {"subpacket": subpacket, "sig": sender_sig},
            matrix_key.publickey().export_key().decode("utf-8"),
        )

    @staticmethod
    def _receiver(matrix_public_key):
        receiver = PacketCryptoMixin()
        receiver.set_logger(lambda *args, **kwargs: None)
        receiver.set_football(_ReceiveFootball(matrix_public_key))
        return receiver

    def test_fresh_authenticated_packet_is_accepted_across_instances(self):
        packet, matrix_public = self._signed_packet()
        first = self._receiver(matrix_public)
        second = self._receiver(matrix_public)

        self.assertEqual({"command": "status"}, first.unpack_secure_packet(packet))
        self.assertEqual({"command": "status"}, second.unpack_secure_packet(packet))
        self.assertTrue(second.has_verified_identity())

    def test_stale_and_future_packets_fail_closed(self):
        now = int(time.time())
        for timestamp in (
            now - 314 - 60,
            now + 314 + 60,
        ):
            with self.subTest(timestamp=timestamp):
                packet, matrix_public = self._signed_packet(timestamp)
                self.assertIsNone(
                    self._receiver(matrix_public).unpack_secure_packet(packet)
                )

    def test_bad_signature_is_rejected_without_affecting_good_packet(self):
        packet, matrix_public = self._signed_packet()
        tampered = deepcopy(packet)
        tampered["subpacket"]["payload"]["command"] = "kill"

        self.assertIsNone(
            self._receiver(matrix_public).unpack_secure_packet(tampered)
        )
        self.assertEqual(
            {"command": "status"},
            self._receiver(matrix_public).unpack_secure_packet(packet),
        )

    def test_both_receivers_accept_fresh_aes_rewrapping_after_restart(self):
        packet, matrix_public = self._signed_packet()
        aes_key = base64.b64encode(b"x" * 32).decode()
        for module in (replay_module, gui_crypto):
            with self.subTest(module=module.__name__):
                def receiver():
                    football = _ReceiveFootball(matrix_public)
                    football.use_symmetric_encryption = lambda: True
                    football.decrypt_aes_key_using_privkey = lambda: False
                    football.get_aes_key = lambda: aes_key
                    result = module.PacketCryptoMixin()
                    result.set_logger(lambda *a, **k: None)
                    return result.set_football(football)
                first = receiver()
                encrypted = first.encrypt_packet(packet, aes_key)
                self.assertEqual({"command": "status"}, first.unpack_secure_packet(encrypted))
                alias = deepcopy(packet)
                alias["sig"] += "\n"
                restarted = receiver()
                self.assertEqual({"command": "status"}, restarted.unpack_secure_packet(restarted.encrypt_packet(alias, aes_key)))
                self.assertTrue(restarted.has_verified_identity())
                self.assertEqual({"command": "status"}, restarted.unpack_secure_packet(restarted.encrypt_packet(packet, aes_key)))

    def test_new_packets_sign_random_nonce_even_with_identical_payload_and_second(self):
        sender_key = RSA.generate(2048)
        class SenderFootball:
            def get_allowed_sender_ids(self): return set()
            def use_payload_identity_file(self): return False
            def use_asymmetric_encryption(self): return False
            def use_symmetric_encryption(self): return False
            def sign_payload(self): return True
            def get_payload_signing_key(self): return sender_key.export_key().decode()
        for module in (replay_module, gui_crypto):
            signer = module.PacketCryptoMixin()
            signer.set_logger(lambda *a, **k: None)
            signer.set_football(SenderFootball())
            with patch.object(module.time, "time", return_value=1000):
                first = signer.build_secure_packet({"command": "status"})
                second = signer.build_secure_packet({"command": "status"})
            self.assertEqual(first["subpacket"]["timestamp"], second["subpacket"]["timestamp"])
            self.assertNotEqual(first["subpacket"]["nonce"], second["subpacket"]["nonce"])
            self.assertNotEqual(first["sig"], second["sig"])
            sp = SigPayloadJson()
            sp.set_payload(first["subpacket"])
            self.assertTrue(signer.verify_payload(sp, sender_key.publickey().export_key().decode(), first["sig"]))
            first["subpacket"]["nonce"] = second["subpacket"]["nonce"]
            sp.set_payload(first["subpacket"])
            self.assertFalse(signer.verify_payload(sp, sender_key.publickey().export_key().decode(), first["sig"]))

    def test_receiver_accepts_fresh_timestamp_from_before_startup(self):
        old, matrix_public = self._signed_packet(1000)
        # Re-signing a genuinely new packet requires its sender key; the test
        # fixture creates an independent valid identity/keypair for that packet.
        fresh, fresh_public = self._signed_packet(1001)
        for module in (replay_module, gui_crypto):
            with patch.object(replay_module.time, "time", return_value=1000.5):
                def receiver(public):
                    football = _ReceiveFootball(public)
                    result = module.PacketCryptoMixin()
                    result.set_logger(lambda *a, **k: None)
                    return result.set_football(football)
                previous = receiver(matrix_public)
                self.assertEqual({"command": "status"}, previous.unpack_secure_packet(old))
                self.assertTrue(previous.has_verified_identity())
                current = receiver(fresh_public)
                self.assertEqual({"command": "status"}, current.unpack_secure_packet(fresh))
                self.assertEqual({"command": "status"}, current.unpack_secure_packet(fresh))

    def test_boot_reload_reads_same_fresh_encrypted_directive_with_children(self):
        from core.python_core.boot_agent import BootAgent
        from core.python_core.class_lib.packet_delivery.utility.encryption.config import ENCRYPTION_CONFIG

        tree = {"universal_id": "sender-1", "name": "matrix", "config": {}, "children": [
            {"universal_id": "matrix-websocket-test", "name": "matrix_websocket", "config": {}, "children": []}
        ]}
        packet, matrix_public = self._signed_packet(1000, {"agent_tree": tree})
        aes_key = base64.b64encode(b"x" * 32).decode()
        encrypted = self._receiver(matrix_public).encrypt_packet(packet, aes_key)

        with TemporaryDirectory() as directory, \
                patch.object(ENCRYPTION_CONFIG, "is_enabled", return_value=True), \
                patch.object(replay_module.time, "time", return_value=1000.75):
            drop = Path(directory) / "sender-1" / "directive"
            drop.mkdir(parents=True)
            saved = drop / "agent_tree_master.json"
            saved.write_text(json.dumps(encrypted), encoding="utf-8")
            original = saved.read_bytes()
            for _ in range(2):
                # Reconstruct the receiver as a fresh Matrix process would.
                agent = BootAgent.__new__(BootAgent)
                agent.matrix_universal_id = "sender-1"
                agent.log = lambda *args, **kwargs: None
                football = _ReceiveFootball(matrix_public)
                football.set_allowed_sender_ids = lambda ids: self.assertEqual(["sender-1"], ids)
                football.use_symmetric_encryption = lambda: True
                football.decrypt_aes_key_using_privkey = lambda: False
                football.get_aes_key = lambda: aes_key
                parsed = agent.load_directive({
                    "path": directory, "address": "sender-1", "drop": "directive", "name": saved.name,
                }, football)
                self.assertEqual(tree, parsed.root)
                self.assertIn("matrix-websocket-test", parsed.nodes)
            self.assertEqual(original, saved.read_bytes())


if __name__ == "__main__":
    unittest.main()
