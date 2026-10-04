"""Timestamp regression tests use synthetic keys and execute no live swarm commands."""
import ast
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from Crypto.PublicKey import RSA

ROOT = Path(__file__).resolve().parents[1]
for folder in ("matrixos", "phoenix"):
    sys.path.insert(0, str(ROOT / folder))

from core.python_core.utils import packet_freshness as server_freshness
from matrix_gui.core.utils import packet_freshness as gui_freshness
from core.python_core.utils import crypto_utils
from core.python_core.class_lib.packet_delivery.utility.security.packet_security import secure_payload
from core.python_core.class_lib.packet_delivery.utility.security import unwrap_secure_packet as server_unwrap
from matrix_gui.core.class_lib.packet_delivery.utility.encryption.utility import unwrap_secure_packet as gui_unwrap


def method(relative, name, namespace):
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    agent = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Agent")
    node = next(node for node in agent.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), relative, "exec"), namespace)
    return namespace[name]


class VerifiedIdentity:
    def has_verified_identity(self):
        return True

    def get_sender_uid(self):
        return "verified-ingress"


class PacketFreshnessTests(unittest.TestCase):
    def test_mirrored_helpers_have_identical_contract(self):
        self.assertEqual(
            (ROOT / "matrixos/core/python_core/utils/packet_freshness.py").read_bytes(),
            (ROOT / "phoenix/matrix_gui/core/utils/packet_freshness.py").read_bytes())


    def test_invalid_timestamps_are_rejected(self):
        for module in (server_freshness, gui_freshness):
            for value in (None, True, "123", float("nan"), float("inf"), {}, 10**400):
                with self.subTest(module=module.__name__, value=type(value)):
                    self.assertFalse(module.packet_is_fresh(value))
                    self.assertTrue(module.packet_is_fresh(time.time()))


    def test_future_packet_is_accepted_within_clock_skew_window(self):
        for module in (server_freshness, gui_freshness):
            self.assertTrue(module.packet_is_fresh(1200, now=1000))
            self.assertTrue(module.packet_is_fresh(1200, now=1400))
            self.assertFalse(module.packet_is_fresh(1200, now=1515))

    def test_signed_expiry_controls_long_lived_packet_freshness(self):
        for module in (server_freshness, gui_freshness):
            self.assertTrue(module.packet_is_fresh(1000, now=1000, expires=1000 + 14*86400))
            self.assertTrue(module.packet_is_fresh(1000, now=1000 + 8*86400, expires=1000 + 14*86400))

    def test_expiry_rejects_future_invalid_and_elapsed_values(self):
        for module in (server_freshness, gui_freshness):
            for ts, end in ((2000, 3000), (1000, 999), (1000, float("nan")),
                            (1000, True), (1, 999)):
                self.assertFalse(module.packet_is_fresh(ts, now=1000, expires=end))
            self.assertTrue(module.packet_is_fresh(1, now=1000, expires=1001))


class AuthenticatedPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sender = RSA.generate(2048)
        cls.receiver = RSA.generate(2048)

    def wrapper(self, *, timestamp=None, expires=None):
        extras = {}
        if expires is not None:
            extras["expires"] = expires
        if timestamp is not None:
            extras["timestamp"] = timestamp
        return {"content": secure_payload(
            {"handler": "cmd_probe", "content": {"probe": "test-only"}},
            self.receiver.publickey().export_key().decode(), signing_key_obj=self.sender,
            extra_fields=extras)}

    def test_websocket_receiver_reload_binds_without_replay_storage(self):
        class Loop:
            def run_until_complete(self, coroutine): return asyncio.run(coroutine)
            def create_task(self, coroutine): coroutine.close()
            def run_forever(self): pass
            def close(self): pass
        class Context:
            def load_verify_locations(self, **kwargs): pass
        events = []
        async def serve(*args, **kwargs):
            events.append("bind")
            async def wait_closed(): pass
            return SimpleNamespace(wait_closed=wait_closed)
        start = method("matrixos/agents/python_core/matrix_websocket/matrix_websocket.py", "start_socket_loop", {
            "time": SimpleNamespace(sleep=lambda *a: None),
            "asyncio": SimpleNamespace(new_event_loop=Loop, set_event_loop=lambda *a: None),
            "ssl": SimpleNamespace(SSLContext=lambda *a: Context(), PROTOCOL_TLS_SERVER=1, CERT_REQUIRED=2),
            "load_cert_chain_from_memory": lambda *a: None,
            "websockets": SimpleNamespace(serve=serve)})
        agent = SimpleNamespace(log=lambda *a, **k: None, _cert_pem="synthetic", _key_pem="synthetic",
            _ca_pem="synthetic", port=0, websocket_handler=None, running=True)
        start(agent)
        self.assertEqual(["bind"], events)
        self.assertTrue(agent.running)

    def test_both_unwrappers_accept_fresh_authenticated_reencoding(self):
        for module in (server_unwrap, gui_unwrap):
            wrapper = self.wrapper()
            self.assertIsInstance(module.unwrap_secure_packet(wrapper, self.sender.publickey(),
                self.receiver.export_key().decode()), dict)
            alias = deepcopy(wrapper)
            alias["content"]["sig"] += "\n"
            self.assertIsInstance(module.unwrap_secure_packet(alias, self.sender.publickey(),
                self.receiver.export_key().decode()), dict)

    def test_tampered_timestamp_is_rejected_without_affecting_good_packet(self):
        wrapper = self.wrapper()
        tampered = deepcopy(wrapper)
        tampered["content"]["timestamp"] += 1
        self.assertFalse(server_unwrap.unwrap_secure_packet(tampered, self.sender.publickey(),
            self.receiver.export_key().decode()))
        self.assertIsInstance(server_unwrap.unwrap_secure_packet(wrapper, self.sender.publickey(),
            self.receiver.export_key().decode()), dict)

    def test_matrix_final_gate_accepts_fresh_packets_across_ingress_and_restart(self):
        command = method("matrixos/agents/python_core/matrix/matrix.py", "cmd_the_source",
            {"IdentityObject": VerifiedIdentity, "unwrap_secure_packet": server_unwrap.unwrap_secure_packet})
        calls = []
        wrapper = self.wrapper()
        def agent():
            return SimpleNamespace(encryption_enabled=True, log=lambda *a, **k: None,
                _signing_keys={"remote_pubkey": self.sender.publickey(), "privkey": self.receiver.export_key().decode()},
                _cmd_probe=lambda *args: calls.append(args))
        original = agent()
        command(original, wrapper, {"ingress": "https"}, VerifiedIdentity())
        alias = deepcopy(wrapper)
        alias["content"]["sig"] += "\n"
        command(original, alias, {"ingress": "ssh"}, VerifiedIdentity())
        command(agent(), wrapper, {"ingress": "email"}, VerifiedIdentity())
        self.assertEqual(3, len(calls))


    def test_matrix_final_gate_accepts_fresh_pre_restart_command(self):
        command = method("matrixos/agents/python_core/matrix/matrix.py", "cmd_the_source",
            {"IdentityObject": VerifiedIdentity, "unwrap_secure_packet": server_unwrap.unwrap_secure_packet})
        calls = []
        agent = SimpleNamespace(encryption_enabled=True, log=lambda *a, **k: None,
            _signing_keys={"remote_pubkey": self.sender.publickey(), "privkey": self.receiver.export_key().decode()},
            _cmd_probe=lambda *args: calls.append(args))
        with patch.object(server_freshness.time, "time", return_value=1000.5):
            command(agent, self.wrapper(timestamp=1000), {}, VerifiedIdentity())
            self.assertEqual(1, len(calls))
            fresh = self.wrapper(timestamp=1001)
            command(agent, fresh, {}, VerifiedIdentity())
            command(agent, fresh, {}, VerifiedIdentity())
            self.assertEqual(3, len(calls))

    def test_https_routes_fresh_signed_transport_repeatedly(self):
        from flask import Flask, jsonify, request
        configure = method("matrixos/agents/python_core/matrix_https/matrix_https.py", "configure_routes",
            {"request": request, "jsonify": jsonify, "time": time, "crypto_utils": crypto_utils,
             "packet_is_fresh": server_freshness.packet_is_fresh,
             "extract_spki_pin_from_cert": lambda _: "fixture-pin", "guard_packet_size": lambda *a, **k: True})
        relays = []
        app = Flask("replay-fixture")
        agent = SimpleNamespace(app=app, allowlist_ips=[], lockdown_state=False,
            _expected_peer_spki="fixture-pin", _peer_pub_key=self.sender.publickey(),
            debug=SimpleNamespace(is_enabled=lambda: False),
            log=lambda *a, **k: None, get_delivery_packet=lambda *a, **k: SimpleNamespace(set_data=lambda data: None),
            get_matrix_universal_id=lambda: "matrix", pass_packet=lambda *a, **k: relays.append(a))
        configure(agent)
        inner = {"ts": time.time(), "matrix_packet": self.wrapper()}
        outer = {"content": inner, "sig": crypto_utils.sign_data(inner, self.sender)}
        with app.test_client() as client:
            env = {"peercert": b"fixture-cert"}
            self.assertEqual(200, client.post("/matrix", json=outer, environ_overrides=env).status_code)
            outer["sig"] += "\n"
            self.assertEqual(200, client.post("/matrix", json=outer, environ_overrides=env).status_code)
        self.assertEqual(2, len(relays))

    def test_websocket_loop_acknowledges_fresh_signed_packets(self):
        import websockets
        loop = method("matrixos/agents/python_core/matrix_websocket/matrix_websocket.py", "_handle_message_loop",
            {"time": time, "json": json, "websockets": websockets, "crypto_utils": crypto_utils,
             "packet_is_fresh": server_freshness.packet_is_fresh,
             "guard_packet_size": lambda *a, **k: True})
        inner = {"ts": time.time(), "fixture": "no-command"}
        outer = {"content": inner, "sig": crypto_utils.sign_data(inner, self.sender)}
        alias = deepcopy(outer)
        alias["sig"] += "\n"
        packets = iter([json.dumps(outer), json.dumps(alias)])
        responses = []
        class Socket:
            async def recv(self):
                try:
                    return next(packets)
                except StopIteration:
                    raise RuntimeError("fixture-end")
            async def send(self, data):
                responses.append(json.loads(data))
            async def close(self, **kwargs):
                pass
        agent = SimpleNamespace(log=lambda *a, **k: None, _peer_pub_key=self.sender.publickey())
        asyncio.run(loop(agent, Socket(), "fixture-session"))
        self.assertEqual(["ack", "ack"], [item["type"] for item in responses])


if __name__ == "__main__":
    unittest.main()
