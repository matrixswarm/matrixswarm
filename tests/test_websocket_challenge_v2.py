"""Strict, connection-bound WSS hello tests for server and both clients."""
import ast
import asyncio
import hmac
import json
import re
from pathlib import Path
import secrets
import sys
import time
import unittest
from unittest.mock import Mock, patch

from Crypto.PublicKey import RSA
import websockets
from websockets.exceptions import InvalidStatus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
sys.path.insert(0, str(ROOT / "phoenix"))
from core.python_core.utils import crypto_utils
from core.python_core.utils.packet_freshness import packet_is_fresh
from matrix_gui.modules.net.connector.ingress.wss import wss as ingress
from matrix_gui.modules.net.connector.wss import wss as other

SOURCE = ROOT / "matrixos/agents/python_core/matrix_websocket/matrix_websocket.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
agent = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Agent")
methods = [node for node in agent.body if isinstance(node, ast.AsyncFunctionDef) and node.name in {"_handle_handshake", "_websocket_handler_core"}]
PROTOCOL = "matrixswarm.hello.v2"
namespace = {"asyncio": asyncio, "hmac": hmac, "json": json, "secrets": secrets,
             "time": time, "crypto_utils": crypto_utils, "packet_is_fresh": packet_is_fresh, "HELLO_PROTOCOL": PROTOCOL,
             "HELLO_TIMEOUT": 1.0, "HELLO_MAX_BYTES": 16384,
             "SESSION_ID_PATTERN": re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")}
namespace["extract_spki_pin_from_cert"] = lambda cert: "client-pin"
exec(compile(ast.Module(body=methods, type_ignores=[]), str(SOURCE), "exec"), namespace)


class ServerProbe:
    _handle_handshake = namespace["_handle_handshake"]

    def __init__(self, public):
        self.command_line_args = {"universal_id": "wss-agent"}
        self._peer_pub_key = public
        self._sessions = {}

    def update_broadcast_flag(self, session_id):
        pass

    def log(self, *args, **kwargs):
        pass


class AsyncSocket:
    def __init__(self, response, subprotocol=PROTOCOL, delay=0):
        self.response = response
        self.subprotocol = subprotocol
        self.delay = delay
        self.challenges = []
        self.reason = None

    async def send(self, data):
        self.challenges.append(json.loads(data))

    async def recv(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.response(self.challenges[-1])

    async def close(self, reason):
        self.reason = reason


class ServerChallengeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = RSA.generate(2048)

    def signed(self, challenge, **changes):
        hello = {"type": "hello", "protocol": PROTOCOL, "agent": "wss-agent",
                 "session_id": "session", "challenge": challenge["challenge"],
                 "nonce": "test", "ts": int(time.time())}
        hello.update(changes)
        hello["sig"] = crypto_utils.sign_data(hello, self.key)
        return json.dumps(hello)

    async def test_valid_hello_is_bound_to_connection_challenge(self):
        probe = ServerProbe(self.key.publickey())
        socket = AsyncSocket(self.signed)
        self.assertEqual(await probe._handle_handshake(socket), "session")
        self.assertEqual(socket.challenges[0]["agent"], "wss-agent")
        self.assertEqual(len(socket.challenges[0]["challenge"]), 64)
        self.assertEqual(socket.challenges[1], {"type": "hello_accepted", "protocol": PROTOCOL,
            "agent": "wss-agent", "session_id": "session", "challenge": socket.challenges[0]["challenge"]})

    async def test_replay_after_new_server_and_empty_cache_is_rejected(self):
        old = []
        def capture(challenge):
            value = self.signed(challenge)
            old.append(value)
            return value
        first = AsyncSocket(capture)
        self.assertEqual(await ServerProbe(self.key.publickey())._handle_handshake(first), "session")
        second = AsyncSocket(lambda challenge: old[0])
        restarted = ServerProbe(self.key.publickey())
        self.assertIsNone(await restarted._handle_handshake(second))
        self.assertEqual(second.reason, "invalid challenge")
        self.assertNotEqual(first.challenges[0]["challenge"], second.challenges[0]["challenge"])

    async def test_no_legacy_or_wrong_target(self):
        legacy = AsyncSocket(self.signed, subprotocol=None)
        self.assertIsNone(await ServerProbe(self.key.publickey())._handle_handshake(legacy))
        self.assertEqual(legacy.reason, "v2 required")
        self.assertEqual(legacy.challenges, [])
        wrong = AsyncSocket(lambda c: self.signed(c, agent="different"))
        self.assertIsNone(await ServerProbe(self.key.publickey())._handle_handshake(wrong))
        self.assertEqual(wrong.reason, "invalid hello")

    async def test_stale_future_or_tampered_signed_hello_is_rejected(self):
        for timestamp in (int(time.time()) - 121, int(time.time()) + 121):
            with self.subTest(timestamp=timestamp):
                socket = AsyncSocket(lambda c: self.signed(c, ts=timestamp))
                self.assertIsNone(await ServerProbe(self.key.publickey())._handle_handshake(socket))
                self.assertEqual(socket.reason, "stale hello")
        def tamper(challenge):
            hello = json.loads(self.signed(challenge))
            hello["session_id"] = "tampered"
            return json.dumps(hello)
        socket = AsyncSocket(tamper)
        self.assertIsNone(await ServerProbe(self.key.publickey())._handle_handshake(socket))
        self.assertEqual(socket.reason, "bad hello signature")

    async def test_session_ids_are_filename_safe_and_bounded(self):
        for value in ("../escape", "session/child", "session\\child", "session\nchild", "", ".hidden", "a" * 129):
            with self.subTest(value=value):
                socket = AsyncSocket(lambda c: self.signed(c, session_id=value))
                self.assertIsNone(await ServerProbe(self.key.publickey())._handle_handshake(socket))
                self.assertEqual(socket.reason, "invalid hello")
        for value in ("session-one", "test.id_01", "00000000-0000-4000-8000-000000000000", "a" * 128):
            with self.subTest(value=value):
                socket = AsyncSocket(lambda c: self.signed(c, session_id=value))
                self.assertEqual(await ServerProbe(self.key.publickey())._handle_handshake(socket), value)

    async def test_missing_or_unsigned_hello_is_rejected(self):
        def unsigned(challenge):
            hello = json.loads(self.signed(challenge))
            del hello["sig"]
            return json.dumps(hello)
        socket = AsyncSocket(unsigned)
        self.assertIsNone(await ServerProbe(self.key.publickey())._handle_handshake(socket))
        self.assertEqual(socket.reason, "missing signature")

    async def test_expired_and_oversized_hello_are_rejected(self):
        delayed = AsyncSocket(self.signed, delay=1.1)
        self.assertIsNone(await ServerProbe(self.key.publickey())._handle_handshake(delayed))
        self.assertEqual(delayed.reason, "handshake failed")
        oversized = AsyncSocket(lambda c: "x" * 16385)
        self.assertIsNone(await ServerProbe(self.key.publickey())._handle_handshake(oversized))
        self.assertEqual(oversized.reason, "invalid hello")

    async def test_real_websocket_negotiation_rejects_no_protocol(self):
        async def handler(ws):
            await ws.close()
        async with websockets.serve(handler, "127.0.0.1", 0, subprotocols=[PROTOCOL]) as server:
            port = server.sockets[0].getsockname()[1]
            with self.assertRaises(InvalidStatus):
                async with websockets.connect(f"ws://127.0.0.1:{port}"):
                    pass
            async with websockets.connect(f"ws://127.0.0.1:{port}", subprotocols=[PROTOCOL]) as ws:
                self.assertEqual(ws.subprotocol, PROTOCOL)

    async def test_old_socket_cleanup_does_not_remove_newer_session(self):
        class CoreProbe:
            _websocket_handler_core = namespace["_websocket_handler_core"]
            def __init__(self, current):
                self.allowlist_ips = []
                self.lockdown_state = False
                self._expected_peer_spki = "client-pin"
                self._sessions = {"session": {"ws": current}}
                self.flags = []
                self.logs = []
            async def _handle_handshake(self, websocket):
                return None
            def update_broadcast_flag(self, **kwargs):
                self.flags.append(kwargs)
            def log(self, value, *args, **kwargs):
                self.logs.append(value)

        class Socket:
            def __init__(self):
                self.session_id = "session"
                self.remote_address = ("127.0.0.1", 1)
                self.transport = Mock()
                self.transport.get_extra_info.return_value.getpeercert.return_value = b"cert"
            async def close(self, **kwargs):
                pass

        old, newer = Socket(), Socket()
        probe = CoreProbe(newer)
        await probe._websocket_handler_core(old)
        self.assertIs(probe._sessions["session"]["ws"], newer)
        self.assertEqual(probe.flags, [])
        self.assertIn("Active=1", probe.logs[-1])
        await probe._websocket_handler_core(newer)
        self.assertEqual(probe._sessions, {})
        self.assertEqual(probe.flags, [{"session_id": "session", "remove": True}])
        self.assertIn("Active=0", probe.logs[-1])


class SyncSocket:
    def __init__(self, challenge, selected=PROTOCOL, receipt=None):
        self.sock = Mock()
        self.sock.getpeercert.return_value = b"synthetic certificate"
        self.selected = selected
        self.challenge = challenge
        self.sent = []
        self.read_count = 0
        self.closed = False
        self.receipt = receipt

    def getsubprotocol(self):
        return self.selected

    def recv(self):
        self.read_count += 1
        if self.read_count == 1:
            return json.dumps(self.challenge)
        if self.receipt is not None:
            return json.dumps(self.receipt)
        hello = self.sent[-1]
        return json.dumps({"type": "hello_accepted", "protocol": PROTOCOL,
            "agent": hello["agent"], "session_id": hello["session_id"], "challenge": hello["challenge"]})

    def send(self, data):
        self.sent.append(json.loads(data))

    def settimeout(self, timeout):
        pass

    def close(self):
        self.closed = True


class ClientChallengeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = RSA.generate(2048)
        cls.agent = {"universal_id": "wss-agent"}
        cls.deployment = {"certs": {"wss-agent": {
            "connection_cert": {"client_cert": {"cert": "cert", "key": "key"},
                                "server_cert": {"spki_pin": "pin"}, "ca_root": {"cert": "ca"}},
            "signing": {"remote_privkey": cls.key.export_key().decode()},
        }}}
        cls.challenge = {"type": "hello_challenge", "protocol": PROTOCOL,
                         "agent": "wss-agent", "challenge": "a" * 64}

    def check_client(self, module, fn, *, challenge=None, pin_ok=True, selected=PROTOCOL, receipt=None):
        socket = SyncSocket(self.challenge if challenge is None else challenge, selected, receipt)
        with patch.object(module, "create_connection", return_value=socket) as connect, \
             patch.object(module, "verify_spki_pin", return_value=(pin_ok, "actual")), \
             patch.object(module.crypto_utils, "sign_data", wraps=module.crypto_utils.sign_data) as signer:
            result = fn("127.0.0.1", 8765, self.agent, self.deployment, "session")
        self.assertEqual(connect.call_count, 1)
        self.assertEqual(connect.call_args.kwargs["subprotocols"], [PROTOCOL])
        return socket, result, signer.call_count

    def test_both_clients_sign_the_challenge(self):
        for module, fn in ((ingress, ingress._establish_connection), (other, other.establish_ws_connection)):
            with self.subTest(module=module.__name__):
                socket, result, count = self.check_client(module, fn)
                self.assertIs(result, socket)
                self.assertEqual(count, 1)
                self.assertEqual(socket.read_count, 2)
                self.assertEqual(socket.sent[0]["challenge"], "a" * 64)
                self.assertEqual(socket.sent[0]["protocol"], PROTOCOL)
                self.assertTrue(crypto_utils.verify_signed_payload(socket.sent[0], socket.sent[0]["sig"], self.key.publickey()))

    def test_pin_or_version_failure_never_reads_challenge_or_signs(self):
        for module, fn in ((ingress, ingress._establish_connection), (other, other.establish_ws_connection)):
            for options in ({"pin_ok": False}, {"selected": None}):
                with self.subTest(module=module.__name__, options=options):
                    socket, result, count = self.check_client(module, fn, **options)
                    self.assertIsNone(result)
                    self.assertEqual(count, 0)
                    self.assertEqual(socket.read_count, 0)
                    self.assertTrue(socket.closed)

    def test_wrong_target_or_malformed_challenge_never_signed(self):
        for module, fn in ((ingress, ingress._establish_connection), (other, other.establish_ws_connection)):
            for challenge in (dict(self.challenge, agent="other"), dict(self.challenge, challenge="bad")):
                with self.subTest(module=module.__name__, challenge=challenge):
                    socket, result, count = self.check_client(module, fn, challenge=challenge)
                    self.assertIsNone(result)
                    self.assertEqual(count, 0)
                    self.assertTrue(socket.closed)

    def test_both_clients_reject_missing_or_mismatched_receipt(self):
        valid = {"type": "hello_accepted", "protocol": PROTOCOL,
                 "agent": "wss-agent", "session_id": "session", "challenge": "a" * 64}
        for module, fn in ((ingress, ingress._establish_connection), (other, other.establish_ws_connection)):
            for receipt in ("", {}, dict(valid, challenge="b" * 64),
                            dict(valid, session_id="other"), dict(valid, protocol="legacy")):
                with self.subTest(module=module.__name__, receipt=receipt):
                    socket, result, count = self.check_client(module, fn, receipt=receipt)
                    self.assertIsNone(result)
                    self.assertEqual(count, 1)
                    self.assertEqual(socket.read_count, 2)
                    self.assertTrue(socket.closed)
