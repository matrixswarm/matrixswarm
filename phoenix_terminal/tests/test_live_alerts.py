"""Disposable keys/vaults and loopback-only WSS; never production credentials."""
import asyncio
import base64
import contextlib
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from phoenix_terminal.alert_access import public_alert, public_alert_page
from phoenix_terminal.cli import build_parser, run_terminal_command
from phoenix_terminal.connection_approval import ApprovalResource
from phoenix_terminal.connection_broker import TerminalConnectionBroker, TerminalSnapshot
from phoenix_terminal.live_alerts import (
    AlertDecoder, LiveAlertFeeds, MAX_FRAME, PacketRejected, PeerIdentityError,
    target_from_deployment, tls_context, verify_peer,
    fixed_target_connector,
)
from phoenix_terminal.terminal_client import TerminalClientIdentity
from phoenix_terminal.terminal_runtime import load_live_toolkit
from phoenix_terminal.terminal_server import TerminalRequestServer

PHOENIX = Path(__file__).resolve().parents[2] / "phoenix"
sys.path.insert(0, str(PHOENIX))
from matrix_gui.modules.vault.crypto.vault_handler import save_vault_singlefile


def canonical(value):
    return json.dumps({k: v for k, v in value.items() if k != "sig"},
                      sort_keys=True, separators=(",", ":")).encode()


def setUpModule():
    global SERVER_SIGN, CLIENT_SIGN, MATERIAL
    SERVER_SIGN, CLIENT_SIGN = RSA.generate(2048), RSA.generate(2048)
    keys = [rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(3)]
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Terminal Test CA")])
    now = datetime.now(timezone.utc)

    def cert(key, name, ca=False, usage=None):
        builder = (x509.CertificateBuilder().subject_name(name).issuer_name(ca_name)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=1))
                   .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
        if usage:
            builder = builder.add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
        return builder.sign(keys[0], hashes.SHA256())

    certs = [cert(keys[0], ca_name, ca=True),
             cert(keys[1], x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fixture Server")]),
                  usage=ExtendedKeyUsageOID.SERVER_AUTH),
             cert(keys[2], x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fixture Client")]),
                  usage=ExtendedKeyUsageOID.CLIENT_AUTH)]
    MATERIAL = {
        "ca": certs[0].public_bytes(serialization.Encoding.PEM).decode(),
        "server": certs[1].public_bytes(serialization.Encoding.PEM).decode(),
        "client": certs[2].public_bytes(serialization.Encoding.PEM).decode(),
        "server_key": keys[1].private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()).decode(),
        "client_key": keys[2].private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()).decode(),
        "pin": base64.b64encode(hashlib.sha256(keys[1].public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode(),
    }


def deployment(host="127.0.0.1", port=1):
    return {
        "label": "Synthetic phoenix",
        "agents": [{"name": "matrix_websocket", "universal_id": "ws-fixture", "serial": "a" * 64,
                    "connection": {"proto": "wss", "channel": "payload.reception", "host": host, "port": port}}],
        "certs": {"ws-fixture": {
            "connection_cert": {"client_cert": {"cert": MATERIAL["client"], "key": MATERIAL["client_key"]},
                                "ca_root": {"cert": MATERIAL["ca"]}, "server_cert": {"spki_pin": MATERIAL["pin"]}},
            "signing": {"pubkey": SERVER_SIGN.public_key().export_key().decode(),
                        "remote_privkey": CLIENT_SIGN.export_key().decode()},
        }},
    }


def target(port=1):
    return target_from_deployment("allowed", deployment(port=port))


def packet(message="BTC fixture token=hide-me", handler="swarm_feed.alert", timestamp=None, **fields):
    payload = {"handler": handler, "content": {"formatted_msg": message, "origin": "crypto-alert",
                                                "level": "critical", "id": "fixture"}}
    key = b"k" * 32
    cipher = AES.new(key, AES.MODE_GCM)
    encoded, tag = cipher.encrypt_and_digest(json.dumps(payload).encode())
    outer = {"serial": "a" * 64, "timestamp": int(time.time()) if timestamp is None else timestamp,
             "content": {"encrypted_key": base64.b64encode(PKCS1_OAEP.new(CLIENT_SIGN.public_key()).encrypt(key)).decode(),
                         "nonce": base64.b64encode(cipher.nonce).decode(), "payload": base64.b64encode(encoded).decode(),
                         "tag": base64.b64encode(tag).decode()}, **fields}
    outer["sig"] = base64.b64encode(pkcs1_15.new(SERVER_SIGN).sign(SHA256.new(canonical(outer)))).decode()
    return json.dumps(outer)


def snapshot():
    return TerminalSnapshot("Synthetic", "c" * 64, (
        ApprovalResource("allowed", "phoenix", ("alerts.read",)),
        ApprovalResource("denied", "backup_service"),
    ), 60)


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("Bounded fixture wait expired")


class SourceTests(unittest.TestCase):
    def test_http_redirects_cannot_change_fixed_target(self):
        connection = fixed_target_connector()(target().uri)
        error = RuntimeError("synthetic redirect")
        self.assertIs(error, connection.process_redirect(error))

    def test_only_fixed_unambiguous_wss_source_is_accepted(self):
        current = target()
        self.assertEqual("wss://127.0.0.1:1/ws", current.uri)
        self.assertNotIn("PRIVATE KEY", repr(current))
        cases = []
        for field, value in (("host", "host/path"), ("host", "host@other"), ("port", True),
                             ("port", 0), ("proto", "ws"), ("channel", "payload.send")):
            data = deployment()
            data["agents"][0]["connection"][field] = value
            cases.append(data)
        data = deployment()
        data["agents"].append(deepcopy(data["agents"][0]))
        cases.append(data)
        data = deployment()
        data["certs"]["ws-fixture"]["connection_cert"]["server_cert"]["spki_pin"] = "bad"
        cases.append(data)
        for data in cases:
            with self.subTest(data_type="invalid source"), self.assertRaises(ValueError):
                target_from_deployment("allowed", data)

    def test_private_targets_are_from_same_vault_revision_and_only_permitted_records(self):
        data = {"deployments": {"allowed": deployment(), "denied": {"label": "backup_service", "agents": []}},
                "registry": {"secret": "SYNTHETIC-HIDDEN"},
                "terminal_access": {"schema_version": 1, "enabled": True, "approval_lifetime_seconds": 60,
                    "permissions": {"alerts.read": {"enabled": True, "deployment_ids": ["allowed"]}}}}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.json"
            with contextlib.redirect_stdout(io.StringIO()):
                save_vault_singlefile(data, "fixture-only", str(path))
            before = path.read_bytes()
            view, targets = load_live_toolkit(PHOENIX, path, "fixture-only")
            self.assertEqual({"allowed"}, set(targets))
            self.assertEqual(before, path.read_bytes())
            self.assertNotIn("PRIVATE KEY", repr(view))
            self.assertNotIn("SYNTHETIC-HIDDEN", repr(view))

    def test_tls_requires_ca_and_cleans_temporary_identity_files(self):
        factory = tempfile.TemporaryDirectory
        paths = []
        def directory(**kwargs):
            result = factory(**kwargs)
            paths.append(result.name)
            return result
        with patch("phoenix_terminal.live_alerts.tempfile.TemporaryDirectory", side_effect=directory):
            context = tls_context(target())
        self.assertEqual(ssl.CERT_REQUIRED, context.verify_mode)
        self.assertTrue(paths and all(not Path(path).exists() for path in paths))


class DecoderTests(unittest.TestCase):
    def test_actual_matrixos_secure_payload_round_trip(self):
        root = Path(__file__).resolve().parents[2] / "matrixos"
        sys.path.insert(0, str(root))
        try:
            from core.python_core.class_lib.packet_delivery.utility.security.packet_security import secure_payload
            value = secure_payload(
                {"handler": "swarm_feed.alert", "content": {"formatted_msg": "Crypto Watch\nBTC fired"}},
                peer_pub_key_pem=CLIENT_SIGN.public_key().export_key().decode(),
                serial_num="a" * 64, signing_key_obj=SERVER_SIGN)
            decoded = AlertDecoder(target()).decode(json.dumps(value))
            self.assertEqual("Crypto Watch\nBTC fired", decoded["content"]["formatted_msg"])
        finally:
            sys.path.remove(str(root))

    def test_real_ciphertext_round_trip_and_replay_rejection(self):
        decoder = AlertDecoder(target())
        wire = packet()
        alert = public_alert(decoder.decode(wire))
        self.assertEqual("CRITICAL", alert["level"])
        self.assertNotIn("hide-me", repr(alert))
        self.assertTrue(alert["timestamp"])
        with self.assertRaises(PacketRejected):
            decoder.decode(wire)

    def test_tampered_wrong_serial_expired_future_plaintext_and_oversize_rejected(self):
        tampered = json.loads(packet())
        tampered["content"]["payload"] = "bad"
        for wire in (json.dumps(tampered), packet(serial="b" * 64), packet(timestamp=1),
                     packet(timestamp=int(time.time()) + 1000), packet(expires=1),
                     '{"handler":"swarm_feed.alert","content":{"msg":"forged"}}',
                     "x" * (MAX_FRAME + 1), "[]"):
            with self.subTest(kind="invalid frame"), self.assertRaises(PacketRejected):
                AlertDecoder(target()).decode(wire)

    def test_authenticated_other_handlers_never_dispatch(self):
        self.assertIsNone(AlertDecoder(target()).decode(packet(handler="shell.exec")))

    def test_rejection_reasons_are_fixed_codes_without_packet_content(self):
        invalid_signature = json.loads(packet())
        invalid_signature["sig"] = "token=PRIVATE-DATA"
        invalid_ciphertext = json.loads(packet())
        invalid_ciphertext["content"]["tag"] = base64.b64encode(b"x" * 16).decode()
        invalid_ciphertext["sig"] = base64.b64encode(pkcs1_15.new(SERVER_SIGN).sign(
            SHA256.new(canonical(invalid_ciphertext)))).decode()
        for wire, reason in (
            ('{"password":"PRIVATE-DATA"}', "MALFORMED_PACKET"),
            (packet(serial="b" * 64), "UNEXPECTED_SENDER"),
            (json.dumps(invalid_signature), "SIGNATURE_INVALID"),
            (packet(timestamp=1), "TIMESTAMP_INVALID"),
            (packet(expires=1), "PACKET_EXPIRED"),
            (json.dumps(invalid_ciphertext), "DECRYPTION_FAILED"),
            ("é" * MAX_FRAME, "FRAME_TOO_LARGE"),
        ):
            with self.subTest(reason=reason), self.assertRaises(PacketRejected) as caught:
                AlertDecoder(target()).decode(wire)
            self.assertEqual(reason, caught.exception.reason)
            self.assertEqual(reason, str(caught.exception))

    def test_verified_alert_is_not_erased_by_later_rejected_traffic(self):
        with MemorySwarm([packet(), "{}", packet(serial="b" * 64)]) as swarm:
            feeds = LiveAlertFeeds({"allowed": target()}, connector=swarm.connect)
            broker = TerminalConnectionBroker(snapshot(), operation_handlers={"alerts.read": feeds.read})
            self.addCleanup(feeds.close)
            self.addCleanup(broker.close)
            broker.handle("connection.request", {"request_id": "fixture", "client_label": "Fixture",
                                                  "client_secret": "s" * 40})
            broker.resolve("fixture", True, "operator approved")
            feeds.start(broker.active_alert_grants)
            wait_for(lambda: feeds.statuses().get("allowed", {}).get("rejected_packets") == 2)
            page = feeds.read("allowed", 0, 100)
            safe = public_alert_page("allowed", 0, 100, page)
            self.assertEqual(1, len(safe["alerts"]))
            self.assertEqual(1, safe["source"]["received_alerts"])
            self.assertEqual("UNEXPECTED_SENDER", safe["source"]["last_rejection"])
            self.assertEqual("PACKET_REJECTED", safe["source"]["code"])
            for changed in ({"last_rejection": "token=PRIVATE-DATA"}, {"received_alerts": -1},
                            {"secret": "PRIVATE-DATA"}):
                forged = {**safe, "source": {**safe["source"], **changed}}
                with self.assertRaisesRegex(RuntimeError, "source status"):
                    public_alert_page("allowed", 0, 100, forged)
            broker.close()
            feeds.close()

    def test_hello_signature_matches_existing_server_contract(self):
        hello = json.loads(AlertDecoder(target()).hello("synthetic-session"))
        self.assertEqual({"type", "session_id", "agent", "ts", "sig"}, set(hello))
        pkcs1_15.new(CLIENT_SIGN.public_key()).verify(SHA256.new(canonical(hello)), base64.b64decode(hello["sig"]))

    def test_non_message_fields_are_also_redacted(self):
        result = public_alert({"origin": "token=hidden", "id": "password=hidden", "msg": "ok"})
        self.assertNotIn("hidden", repr(result))


class LocalSwarm:
    """Real mTLS WSS server bound exclusively to ephemeral IPv4 loopback."""
    def __init__(self, frames=None):
        self.frames = [packet()] if frames is None else frames
        self.ready, self.stop = threading.Event(), threading.Event()
        self.connections = 0
        self.hellos = []
        self.error = None
        self.port = None

    def __enter__(self):
        self.thread = threading.Thread(target=self._thread, daemon=True)
        self.thread.start()
        if not self.ready.wait(5) or self.error:
            raise AssertionError("Loopback TLS fixture startup failed") from self.error
        return self

    def _thread(self):
        try:
            asyncio.run(self._run())
        except Exception as exc:
            self.error = exc
            self.ready.set()

    async def _run(self):
        with tempfile.TemporaryDirectory() as temporary:
            cert, key = Path(temporary) / "server.pem", Path(temporary) / "server.key"
            cert.write_text(MATERIAL["server"])
            key.write_text(MATERIAL["server_key"])
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            context.load_verify_locations(cadata=MATERIAL["ca"])
            context.verify_mode = ssl.CERT_REQUIRED

            async def handler(ws):
                self.connections += 1
                try:
                    hello = json.loads(await ws.recv())
                    pkcs1_15.new(CLIENT_SIGN.public_key()).verify(
                        SHA256.new(canonical(hello)), base64.b64decode(hello["sig"]))
                    self.hellos.append(hello)
                    for wire in self.frames:
                        await ws.send(wire)
                    await ws.wait_closed()
                except ConnectionClosed:
                    pass
            async with serve(handler, "127.0.0.1", 0, ssl=context, close_timeout=1) as server:
                self.port = server.sockets[0].getsockname()[1]
                self.ready.set()
                while not self.stop.is_set():
                    await asyncio.sleep(0.02)

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(3)
        if self.thread.is_alive():
            raise AssertionError("Loopback fixture failed to stop")


class MemorySwarm:
    """Real TLS via SSL MemoryBIO, simulated WebSocket framing, no OS TLS interception."""
    def __init__(self, frames=None):
        self.frames = [packet()] if frames is None else frames
        self.connections, self.hellos, self.port = 0, [], 1

    def __enter__(self):
        self.directory = tempfile.TemporaryDirectory()
        cert = Path(self.directory.name) / "server.pem"
        key = Path(self.directory.name) / "server.key"
        cert.write_text(MATERIAL["server"])
        key.write_text(MATERIAL["server_key"])
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(cert, key)
        self.context.load_verify_locations(cadata=MATERIAL["ca"])
        self.context.verify_mode = ssl.CERT_REQUIRED
        return self

    def __exit__(self, *_):
        self.directory.cleanup()

    @contextlib.asynccontextmanager
    async def connect(self, uri, **kwargs):
        owner = self
        class Connection:
            def __init__(self):
                self.cin, self.cout, self.sin, self.sout = [ssl.MemoryBIO() for _ in range(4)]
                self.client = kwargs["ssl"].wrap_bio(self.cin, self.cout, server_side=False)
                self.server = owner.context.wrap_bio(self.sin, self.sout, server_side=True)
                ready = set()
                for _ in range(20):
                    for side in (self.client, self.server):
                        try:
                            side.do_handshake()
                            ready.add(side)
                        except ssl.SSLWantReadError:
                            pass
                        self.pump()
                    if len(ready) == 2:
                        break
                if len(ready) != 2:
                    raise AssertionError("TLS MemoryBIO handshake failed")
                self.transport = self
                self.frames = iter(owner.frames)
                owner.connections += 1

            def pump(self):
                for output, incoming in ((self.cout, self.sin), (self.sout, self.cin)):
                    if output.pending:
                        incoming.write(output.read())

            def get_extra_info(self, name):
                return self.client if name == "ssl_object" else None

            async def send(self, wire):
                self.client.write(wire.encode())
                self.pump()
                hello = json.loads(self.server.read())
                pkcs1_15.new(CLIENT_SIGN.public_key()).verify(
                    SHA256.new(canonical(hello)), base64.b64decode(hello["sig"]))
                owner.hellos.append(hello)

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    wire = next(self.frames)
                except StopIteration:
                    await asyncio.Event().wait()
                    raise StopAsyncIteration
                self.server.write(wire.encode())
                self.pump()
                return self.client.read(MAX_FRAME).decode()
        yield Connection()


class LiveTests(unittest.TestCase):
    def test_supervisor_failure_is_visible_not_permanently_starting(self):
        feeds = LiveAlertFeeds({"allowed": target()})
        self.addCleanup(feeds.close)
        async def broken_supervisor():
            raise TypeError("token=DO-NOT-LEAK")
        with patch.object(feeds, "_supervise", side_effect=broken_supervisor), contextlib.redirect_stderr(io.StringIO()) as output:
            feeds.start(lambda: {"allowed": (("fixture", 123),)})
            feeds._thread.join(2)
        self.assertFalse(feeds._thread.is_alive())
        self.assertEqual("WORKER_FAILED", feeds.statuses()["Alert worker"]["code"])
        with self.assertRaisesRegex(ValueError, "worker failed"):
            feeds.read("allowed", 0, 50)
        self.assertIn("TypeError", output.getvalue())
        self.assertNotIn("DO-NOT-LEAK", output.getvalue())

    def start(self, port, **kwargs):
        feeds = LiveAlertFeeds({"allowed": target(port)}, **kwargs)
        broker = TerminalConnectionBroker(snapshot(), operation_handlers={"alerts.read": feeds.read})
        feeds.start(broker.active_alert_grants)
        self.addCleanup(feeds.close)
        self.addCleanup(broker.close)
        return feeds, broker

    def approve(self, broker, request_id="fixture-request"):
        broker.handle("connection.request", {"request_id": request_id, "client_label": "Fixture",
                                              "client_secret": "s" * 40})
        broker.resolve(request_id, True, "test operator approved")

    def read(self, broker, **params):
        return broker.handle("alerts.read", {"request_id": "fixture-request", "client_secret": "s" * 40,
                           "deployment_id": "allowed", "after": 0, "limit": 100, **params})

    def test_real_tls_hello_alert_scoping_and_disconnect_over_loopback_cli(self):
        with MemorySwarm() as swarm, tempfile.TemporaryDirectory() as temporary:
            feeds, broker = self.start(swarm.port, connector=swarm.connect)
            server = TerminalRequestServer(broker.handle, Path(temporary))
            server.start()
            self.addCleanup(server.stop)
            identity = TerminalClientIdentity(temporary)
            result = identity.request("Fixture client")
            time.sleep(0.2)
            self.assertEqual(0, swarm.connections)
            self.assertEqual([], result["resources"])
            with self.assertRaisesRegex(RuntimeError, "not approved"):
                identity.read_alerts("allowed")
            broker.resolve(result["request_id"], True, "test operator approved")
            wait_for(lambda: feeds.statuses().get("allowed", {}).get("code") == "RECEIVING_ALERTS")
            status = identity.status()
            self.assertEqual(["allowed"], [r["deployment_id"] for r in status["resources"]])
            args = build_parser().parse_args(["--data-dir", temporary, "terminal", "alerts", "allowed"])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(0, run_terminal_command(args))
            page = json.loads(output.getvalue())
            self.assertEqual("connected", page["source"]["state"])
            self.assertEqual(1, len(page["alerts"]))
            self.assertNotIn("hide-me", output.getvalue())
            self.assertEqual("hello", swarm.hellos[0]["type"])
            with self.assertRaisesRegex(RuntimeError, "not allowed"):
                identity.read_alerts("denied")
            for method in ("alerts.delete", "agent.restart", "shell.exec"):
                with self.assertRaises(PermissionError):
                    broker.handle(method, {})
            cursor, stream = page["next_cursor"], page["source"]["stream_id"]
            with self.assertRaisesRegex(RuntimeError, "stream_id"):
                identity.read_alerts("allowed", after=cursor)
            self.assertEqual([], identity.read_alerts("allowed", after=cursor, stream_id=stream)["alerts"])
            identity.disconnect()
            wait_for(lambda: not feeds.statuses())
            self.assertEqual({}, broker.active_alert_grants())
            self.assertFalse(identity.path.exists())
            feeds.close()
            self.assertFalse(feeds._thread.is_alive())

    def test_wrong_pin_never_sends_hello_or_releases_alerts(self):
        with MemorySwarm() as swarm:
            feeds = LiveAlertFeeds({"allowed": replace(target(swarm.port), server_pin=base64.b64encode(b"x" * 32).decode())}, connector=swarm.connect)
            broker = TerminalConnectionBroker(snapshot(), operation_handlers={"alerts.read": feeds.read})
            self.addCleanup(feeds.close)
            self.addCleanup(broker.close)
            feeds.start(broker.active_alert_grants)
            self.approve(broker)
            wait_for(lambda: feeds.statuses().get("allowed", {}).get("state") == "error")
            page = self.read(broker)
            self.assertEqual("PEER_IDENTITY_FAILED", page["source"]["code"])
            self.assertEqual([], page["alerts"])
            self.assertEqual([], swarm.hellos)
            broker.close()
            feeds.close()

    def test_expiry_revokes_without_gui_timer_or_client_polling(self):
        now = [10.0]
        with MemorySwarm() as swarm:
            feeds = LiveAlertFeeds({"allowed": target(swarm.port)}, connector=swarm.connect)
            broker = TerminalConnectionBroker(snapshot(), clock=lambda: now[0], operation_handlers={"alerts.read": feeds.read})
            self.addCleanup(feeds.close)
            self.addCleanup(broker.close)
            feeds.start(broker.active_alert_grants)
            self.approve(broker)
            wait_for(lambda: bool(swarm.hellos))
            now[0] = 71
            wait_for(lambda: not feeds.statuses())
            with self.assertRaisesRegex(PermissionError, "not approved"):
                self.read(broker)
            feeds.close()

    def test_failed_network_is_visible_and_no_raw_exception_leaks(self):
        @contextlib.asynccontextmanager
        async def broken(*args, **kwargs):
            raise OSError("token=THIS-MUST-NOT-LEAK")
            yield
        feeds, broker = self.start(1, connector=broken, context_factory=lambda _: object())
        self.approve(broker)
        wait_for(lambda: feeds.statuses().get("allowed", {}).get("state") == "reconnecting")
        page = self.read(broker)
        self.assertEqual("CONNECTION_FAILED", page["source"]["code"])
        self.assertTrue(page["source"]["may_have_missed"])
        self.assertNotIn("THIS-MUST-NOT-LEAK", repr(page))

    def test_rejected_packets_and_plaintext_are_not_alerts(self):
        with MemorySwarm(["{}", packet(), packet(handler="agent.log")]) as swarm:
            feeds, broker = self.start(swarm.port, connector=swarm.connect)
            self.approve(broker)
            wait_for(lambda: feeds.statuses().get("allowed", {}).get("code") == "RECEIVING_ALERTS")
            page = self.read(broker)
            self.assertEqual(1, page["source"]["rejected_packets"])
            self.assertEqual(1, len(page["alerts"]))
            broker.close()
            feeds.close()

    def test_close_cancels_inflight_connect_promptly(self):
        entered = threading.Event()
        @contextlib.asynccontextmanager
        async def hanging(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
            yield
        feeds, broker = self.start(1, connector=hanging, context_factory=lambda _: object())
        self.approve(broker)
        self.assertTrue(entered.wait(3))
        started = time.monotonic()
        broker.close()
        feeds.close()
        self.assertLess(time.monotonic() - started, 2)
        self.assertFalse(feeds._thread.is_alive())

    def test_reapproval_rotates_stream_and_rejects_old_cursors(self):
        with MemorySwarm() as swarm:
            feeds, broker = self.start(swarm.port, connector=swarm.connect)
            self.approve(broker)
            wait_for(lambda: feeds.statuses().get("allowed", {}).get("code") == "RECEIVING_ALERTS")
            old = self.read(broker)["source"]["stream_id"]
            with broker._lock:  # Prevent supervisor racing the deterministic stale-buffer assertion.
                broker.handle("connection.disconnect", {"request_id": "fixture-request", "client_secret": "s" * 40})
                self.approve(broker, "new-request")
                with self.assertRaisesRegex(ValueError, "starting"):
                    feeds.read("allowed", 0, 100)
            wait_for(lambda: len(swarm.hellos) == 2)
            wait_for(lambda: feeds.statuses().get("allowed", {}).get("code") == "RECEIVING_ALERTS")
            with self.assertRaisesRegex(ValueError, "stream changed"):
                self.read(broker, request_id="new-request", stream_id=old)
            self.assertNotEqual(old, self.read(broker, request_id="new-request")["source"]["stream_id"])
            broker.close()
            feeds.close()

    def test_parameter_overrides_fail_before_reader(self):
        from unittest.mock import Mock
        reader = Mock()
        broker = TerminalConnectionBroker(snapshot(), operation_handlers={"alerts.read": reader})
        self.addCleanup(broker.close)
        self.approve(broker)
        for field in ("host", "port", "credential", "target", "handler", "approve"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.read(broker, **{field: "forged"})
        reader.assert_not_called()

    def test_expiry_during_adapter_read_never_releases_result(self):
        now = [0.0]
        from phoenix_terminal.alert_access import TerminalAlertBuffer
        def late(deployment_id, after, limit):
            now[0] = 61
            return TerminalAlertBuffer().read(deployment_id, after, limit)
        broker = TerminalConnectionBroker(snapshot(), clock=lambda: now[0], operation_handlers={"alerts.read": late})
        self.addCleanup(broker.close)
        self.approve(broker)
        with self.assertRaisesRegex(PermissionError, "expired during read"):
            self.read(broker)

    def test_adapter_programming_error_is_not_mislabeled_network_failure(self):
        @contextlib.asynccontextmanager
        async def broken(*args, **kwargs):
            raise TypeError("synthetic implementation failure")
            yield
        feeds, broker = self.start(1, connector=broken, context_factory=lambda _: object())
        with contextlib.redirect_stderr(io.StringIO()) as diagnostic:
            self.approve(broker)
            wait_for(lambda: feeds.statuses().get("allowed", {}).get("code") == "WORKER_FAILED")
            broker.close()
            feeds.close()
        self.assertIn("TypeError", diagnostic.getvalue())
        self.assertNotIn("synthetic implementation failure", diagnostic.getvalue())

    @unittest.skipIf(os.environ.get("PHOENIX_TEST_SKIP_LOOPBACK_TLS") == "1",
                     "Explicit local diagnostic override: antivirus substitutes loopback TLS certificate; run on clean CI")
    def test_real_socket_websocket_framing_and_mtls(self):
        with LocalSwarm() as swarm:
            feeds, broker = self.start(swarm.port)
            self.approve(broker)
            try:
                wait_for(lambda: feeds.statuses().get("allowed", {}).get("code") == "RECEIVING_ALERTS")
                self.assertEqual(1, len(self.read(broker)["alerts"]))
                self.assertEqual("hello", swarm.hellos[0]["type"])
            finally:
                broker.close()
                feeds.close()


if __name__ == "__main__":
    unittest.main()
