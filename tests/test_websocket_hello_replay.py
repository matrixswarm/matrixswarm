"""Freshness and replay coverage for strict connection-bound WSS hellos."""
import asyncio
import json
import time
import unittest
from unittest.mock import patch

from Crypto.PublicKey import RSA
from tests.test_websocket_challenge_v2 import AsyncSocket, PROTOCOL, ServerProbe
from core.python_core.utils import crypto_utils


class WebSocketHelloReplayTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = RSA.generate(2048)

    def hello(self, challenge_message, **changes):
        hello = {"type": "hello", "protocol": PROTOCOL, "agent": "wss-agent",
                 "session_id": "session", "challenge": challenge_message["challenge"],
                 "nonce": "test", "ts": int(time.time())}
        hello.update(changes)
        hello["sig"] = crypto_utils.sign_data(hello, self.key)
        return json.dumps(hello)

    async def test_independent_hellos_reconnect_with_unique_challenges(self):
        sockets = [AsyncSocket(self.hello) for _ in range(12)]
        results = await asyncio.gather(*(ServerProbe(self.key.publickey())._handle_handshake(s) for s in sockets))
        self.assertEqual(results, ["session"] * len(sockets))
        self.assertEqual(len({s.challenges[0]["challenge"] for s in sockets}), len(sockets))

    async def test_old_hello_cannot_be_retargeted_to_new_challenge(self):
        captured = []
        def first(challenge):
            encoded = self.hello(challenge)
            captured.append(json.loads(encoded))
            return encoded
        first_socket = AsyncSocket(first)
        self.assertEqual(await ServerProbe(self.key.publickey())._handle_handshake(first_socket), "session")
        def retarget(challenge):
            changed = dict(captured[0], challenge=challenge["challenge"])
            return json.dumps(changed)
        second = AsyncSocket(retarget)
        self.assertIsNone(await ServerProbe(self.key.publickey())._handle_handshake(second))
        self.assertEqual(second.reason, "bad hello signature")

    async def test_v1_hello_is_rejected_even_with_a_valid_signature(self):
        socket = AsyncSocket(lambda c: self.hello(c), subprotocol=None)
        self.assertIsNone(await ServerProbe(self.key.publickey())._handle_handshake(socket))
        self.assertEqual(socket.reason, "v2 required")
        self.assertEqual(socket.challenges, [])

    async def test_timestamp_window_is_still_enforced_after_signature(self):
        for timestamp, accepted in ((int(time.time()) - 119, True),
                                    (int(time.time()) - 121, False),
                                    (int(time.time()) + 121, False), (None, False)):
            with self.subTest(timestamp=timestamp):
                socket = AsyncSocket(lambda c: self.hello(c, ts=timestamp))
                result = await ServerProbe(self.key.publickey())._handle_handshake(socket)
                self.assertEqual(result == "session", accepted)
                if not accepted:
                    self.assertEqual(socket.reason, "stale hello")

    async def test_v2_does_not_depend_on_sqlite_availability(self):
        socket = AsyncSocket(self.hello)
        with patch("sqlite3.connect", side_effect=OSError("read-only disk")):
            self.assertEqual(await ServerProbe(self.key.publickey())._handle_handshake(socket), "session")

    async def test_malformed_or_missing_challenge_fails_closed(self):
        for value in (None, "", "z" * 64, "a" * 63, "é" * 64):
            with self.subTest(value=value):
                socket = AsyncSocket(lambda c: self.hello(c, challenge=value))
                self.assertIsNone(await ServerProbe(self.key.publickey())._handle_handshake(socket))
                self.assertEqual(socket.reason, "invalid challenge")
