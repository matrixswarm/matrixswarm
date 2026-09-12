"""Exercise real agent handlers without booting a swarm or opening sockets."""
import ast
from copy import deepcopy
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
sys.path.insert(0, str(ROOT / "matrixos" / "agents" / "python_core"))
from crypto_alert.engine import AlertEngine
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from core.python_core.class_lib.packet_delivery.packet.standard.command.packet import Packet as Command
from core.python_core.class_lib.packet_delivery.packet.notify.alert.general import Packet as Notice
from core.python_core.class_lib.gui.callback_dispatcher import CallbackCtx, PhoenixCallbackDispatcher


def load_agent():
    path = ROOT / "matrixos/agents/python_core/crypto_alert/crypto_alert.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Agent")
    cls.bases = []  # BootAgent constructor is deliberately outside this unit test.
    namespace = {"IdentityObject": IdentityObject, "re": re, "time": time}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), "exec"), namespace)
    return namespace["Agent"]


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        cls = load_agent()
        self.agent = cls.__new__(cls)
        self.agent.command_line_args = {"universal_id": "crypto-one"}
        self.agent.get_matrix_universal_id = lambda: "matrix-new-id"
        self.agent._rpc_role = "hive.rpc"
        self.agent._alert_role = "hive.alert"
        self.agent._streams = {}
        self.agent._stream_lock = threading.RLock()
        self.agent._last_stream = 0
        self.agent.log = Mock()
        self.replies, self.saved = [], []
        self.agent.crypto_reply = lambda **kwargs: self.replies.append(kwargs)
        feed = Mock()
        feed.status.return_value = "live"
        self.agent.engine = AlertEngine(feed, Mock(), lambda doc: self.saved.append(deepcopy(doc)), Mock())
        self.identity = IdentityObject(True, "matrix-new-id")
        self.content = {"target_universal_id": "crypto-one", "session_id": "session-a",
                        "token": "token-a", "request_id": "request-a", "revision": 0, "watch_list": []}

    def test_verified_matrix_identity_and_exact_target_required(self):
        for identity in (None, IdentityObject(False, "matrix-new-id"), IdentityObject(True, "other")):
            self.agent.cmd_update_alerts(self.content, None, identity)
        self.agent.cmd_update_alerts(dict(self.content, target_universal_id="crypto-two"), None, self.identity)
        self.assertEqual(self.replies, [])
        self.assertEqual(len(self.saved), 1)
        self.agent.cmd_update_alerts(self.content, None, self.identity)
        self.assertTrue(self.replies[-1]["payload"]["ok"])
        self.assertEqual(self.replies[-1]["payload"]["revision"], 1)
        self.assertEqual(self.replies[-1]["payload"]["agent_uid"], "crypto-one")
        self.assertTrue(self.replies[-1]["quiet"])

    def test_disk_failure_and_revision_conflict_return_failure_ack(self):
        self.agent.engine.persist = Mock(side_effect=OSError("disk full"))
        self.agent.cmd_update_alerts(self.content, None, self.identity)
        self.assertFalse(self.replies[-1]["payload"]["ok"])
        self.assertEqual(self.agent.engine.snapshot()["revision"], 0)
        self.agent.cmd_update_alerts(dict(self.content, revision=99), None, self.identity)
        self.assertIn("reload", self.replies[-1]["payload"]["error"])

    def test_subscription_renewal_stop_and_expiry_are_scoped(self):
        self.agent.cmd_stream_prices(self.content, None, self.identity)
        self.agent.cmd_stream_prices(self.content, None, self.identity)
        self.agent.cmd_stream_prices(dict(self.content, token="token-b"), None, self.identity)
        self.assertEqual(len(self.agent._streams), 2)
        self.agent.cmd_stop_stream_prices(self.content, None, self.identity)
        self.assertEqual(list(self.agent._streams), [("session-a", "token-b")])
        self.agent.worker()
        self.assertEqual(self.replies[-1]["response_handler"], "crypto_alert.update")
        self.assertEqual(self.replies[-1]["payload"]["token"], "token-b")
        self.agent._streams[("session-a", "token-b")] = (self.content, time.monotonic()-1)
        self.agent._last_stream = 0
        self.agent.worker()
        self.assertEqual(self.agent._streams, {})

    def test_notification_payload_survives_nested_packet_serialization(self):
        endpoint = Mock()
        endpoint.get_handler.return_value = "cmd_alert"
        endpoint.get_universal_id.return_value = "relay-uuid"
        self.agent.get_nodes_by_role = lambda role: [endpoint]
        self.agent.get_delivery_packet = lambda name: Notice() if name == "notify.alert.general" else Command()
        sent = []
        def deliver(packet, target):
            sent.append(packet.get_packet())
            self.assertEqual(target, "relay-uuid")
            return True
        self.agent.pass_packet = deliver
        self.assertTrue(self.agent.send_simple_alert("BTC/ETH crossed 20"))
        self.assertEqual(sent[0]["content"]["msg"], "BTC/ETH crossed 20")
        self.agent.pass_packet = lambda *args: False
        self.assertFalse(self.agent.send_simple_alert("BTC/ETH crossed 21"))

    def test_quiet_callback_suppresses_routine_logs_and_never_logs_payload(self):
        agent = Mock()
        agent.tree_node = {}
        agent.command_line_args = {"universal_id": "crypto-one"}
        endpoint = Mock()
        endpoint.get_handler.return_value = "cmd_rpc_route"
        endpoint.get_universal_id.return_value = "websocket-one"
        agent.get_nodes_by_role.return_value = [endpoint]
        agent.get_delivery_packet.return_value = Command()
        dispatcher = PhoenixCallbackDispatcher(agent)
        context = CallbackCtx(
            agent=agent, rpc_role="hive.rpc", signing_key=object(),
            remote_pub_pem=b"fixture", serial="a" * 64,
            response_handler="crypto_alert.update", confirm_response=True,
        )
        with patch("core.python_core.class_lib.gui.callback_dispatcher.encrypt_with_ephemeral_aes", return_value={"sealed": True}), \
             patch("core.python_core.class_lib.gui.callback_dispatcher.sign_data", return_value="sig"):
            dispatcher.dispatch(context, {"secret": "must-not-be-logged"}, quiet=True)
            agent.log.assert_not_called()
            dispatcher.dispatch(context, {"secret": "must-not-be-logged"}, quiet=False)
        self.assertNotIn("must-not-be-logged", str(agent.log.call_args_list))

    def test_session_callback_routes_only_to_relay_that_owns_session(self):
        agent = Mock()
        agent.tree_node = {"config": {}}
        agent.command_line_args = {"universal_id": "crypto-one"}
        websocket = Mock()
        websocket.get_handler.return_value = "cmd_rpc_route"
        websocket.get_universal_id.return_value = "websocket-one"
        email = Mock()
        email.get_handler.return_value = "cmd_rpc_route"
        email.get_universal_id.return_value = "email-one"
        agent.get_nodes_by_role.return_value = [websocket, email]
        agent.get_delivery_packet.return_value = Command()

        with tempfile.TemporaryDirectory() as comm_path:
            agent.path_resolution = {"comm_path": comm_path}
            flag_dir = Path(comm_path) / "websocket-one" / "broadcast"
            flag_dir.mkdir(parents=True)
            (flag_dir / "connected.flag.session-a").touch()

            context = CallbackCtx(
                agent=agent, rpc_role="hive.rpc", signing_key=object(),
                remote_pub_pem=b"fixture", serial="a" * 64,
                response_handler="crypto_alert.update", confirm_response=True,
                session_id="session-a",
            )
            dispatcher = PhoenixCallbackDispatcher(agent)
            with patch("core.python_core.class_lib.gui.callback_dispatcher.encrypt_with_ephemeral_aes", return_value={"sealed": True}), \
                 patch("core.python_core.class_lib.gui.callback_dispatcher.sign_data", return_value="sig"):
                dispatcher.dispatch(context, {"price": 78000}, quiet=True)

        agent.pass_packet.assert_called_once()
        self.assertEqual(agent.pass_packet.call_args.args[1], "websocket-one")

    def test_session_callback_rejects_stale_or_unowned_relay(self):
        agent = Mock()
        agent.tree_node = {"config": {"callback_session_flag_max_age": 5}}
        agent.command_line_args = {"universal_id": "crypto-one"}
        endpoint = Mock()
        endpoint.get_handler.return_value = "cmd_rpc_route"
        endpoint.get_universal_id.return_value = "websocket-one"
        agent.get_nodes_by_role.return_value = [endpoint]
        agent.get_delivery_packet.return_value = Command()

        with tempfile.TemporaryDirectory() as comm_path:
            agent.path_resolution = {"comm_path": comm_path}
            flag_dir = Path(comm_path) / "websocket-one" / "broadcast"
            flag_dir.mkdir(parents=True)
            flag = flag_dir / "connected.flag.session-a"
            flag.touch()
            old = time.time() - 10
            os.utime(flag, (old, old))

            context = CallbackCtx(
                agent=agent, rpc_role="hive.rpc", signing_key=object(),
                remote_pub_pem=b"fixture", serial="a" * 64,
                response_handler="crypto_alert.update", confirm_response=True,
                session_id="session-a",
            )
            dispatcher = PhoenixCallbackDispatcher(agent)
            with patch("core.python_core.class_lib.gui.callback_dispatcher.encrypt_with_ephemeral_aes") as encrypt:
                dispatcher.dispatch(context, {"price": 78000}, quiet=True)

        agent.pass_packet.assert_not_called()
        encrypt.assert_not_called()

    def test_email_egress_defensive_disposal_log_is_rate_limited(self):
        path = ROOT / "matrixos/agents/python_core/matrix_email_egress/matrix_email_egress.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "_log_disposed_session")
        clock = Mock()
        clock.monotonic.side_effect = [100.0, 110.0, 161.0]
        namespace = {"time": clock}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                     str(path), "exec"), namespace)
        egress = Mock()
        egress._disposed_log_at = {}

        for _ in range(3):
            namespace["_log_disposed_session"](egress, "session-a", "crypto-one")

        self.assertEqual(egress.log.call_count, 2)

    def test_matrix_routes_only_to_target_and_does_not_log_wallet_payload(self):
        path = ROOT / "matrixos/agents/python_core/matrix/matrix.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "_cmd_service_request")
        namespace = {"time": time, "IdentityObject": IdentityObject}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(path), "exec"), namespace)
        matrix = Mock()
        matrix.command_line_args = {"universal_id": "matrix-new-id"}
        endpoints = []
        for uid in ("crypto-one", "crypto-two"):
            ep = Mock()
            ep.get_universal_id.return_value = uid
            ep.get_handler.return_value = "cmd_update_alerts"
            endpoints.append(ep)
        matrix.get_nodes_by_role.return_value = endpoints
        matrix.get_delivery_packet.side_effect = lambda name: Command()
        payload = dict(self.content, address="private-watch-address-fixture")
        namespace["_cmd_service_request"](matrix, {"service": "hive.crypto_alert.update_config", "payload": payload}, None)
        matrix.pass_packet.assert_called_once()
        self.assertEqual(matrix.pass_packet.call_args.args[1], "crypto-one")
        self.assertNotIn("private-watch-address-fixture", str(matrix.log.call_args_list))
        # Other service routing retains its existing fan-out behavior.
        matrix.pass_packet.reset_mock()
        namespace["_cmd_service_request"](matrix, {"service": "hive.example", "payload": {}}, None)
        self.assertEqual(matrix.pass_packet.call_count, 2)


if __name__ == "__main__":
    unittest.main()
