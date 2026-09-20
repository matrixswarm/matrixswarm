import sys
import time
import unittest
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from Crypto.PublicKey import RSA


ROOT = Path(__file__).resolve().parents[1]
MATRIXOS = ROOT / "matrixos"
if str(MATRIXOS) not in sys.path:
    sys.path.insert(0, str(MATRIXOS))

from core.python_core.class_lib.packet_delivery.utility.encryption import packet_crypto_mixin as replay_module
from core.python_core.class_lib.packet_delivery.utility.encryption.packet_crypto_mixin import PacketCryptoMixin
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.sig_payload_json import SigPayloadJson


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
    def setUp(self):
        with replay_module._replay_lock:
            replay_module._replay_cache.clear()

    @staticmethod
    def _signed_packet(timestamp=None):
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
            "payload": {"command": "status"},
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

    def test_fresh_authenticated_packet_is_accepted_once_across_instances(self):
        packet, matrix_public = self._signed_packet()
        first = self._receiver(matrix_public)
        second = self._receiver(matrix_public)

        self.assertEqual({"command": "status"}, first.unpack_secure_packet(packet))
        self.assertIsNone(second.unpack_secure_packet(packet))
        self.assertFalse(second.has_verified_identity())

    def test_stale_and_future_packets_fail_closed(self):
        now = int(time.time())
        for timestamp in (
            now - replay_module._REPLAY_TTL - 60,
            now + replay_module._REPLAY_TTL + 60,
        ):
            with self.subTest(timestamp=timestamp):
                packet, matrix_public = self._signed_packet(timestamp)
                self.assertIsNone(
                    self._receiver(matrix_public).unpack_secure_packet(packet)
                )

    def test_bad_signature_cannot_poison_replay_cache(self):
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

    def test_duplicate_check_is_atomic_and_cache_is_bounded(self):
        now = int(time.time())
        with ThreadPoolExecutor(max_workers=8) as pool:
            accepted = list(
                pool.map(
                    lambda _: replay_module._replay_block("same-signature", now),
                    range(32),
                )
            )
        self.assertEqual(1, accepted.count(True))

        with replay_module._replay_lock:
            replay_module._replay_cache.clear()
        with patch.object(replay_module, "_REPLAY_CACHE_LIMIT", 3):
            for index in range(8):
                self.assertTrue(
                    replay_module._replay_block(f"signature-{index}", now)
                )
        self.assertEqual(3, len(replay_module._replay_cache))


if __name__ == "__main__":
    unittest.main()
