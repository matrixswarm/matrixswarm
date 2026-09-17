import unittest
import threading
import time
import json
import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from phoenix_terminal.bridge.server import BridgeServer
from phoenix_terminal.bridge_client import call_bridge
from phoenix_terminal.bridge.phoenix_backend import PhoenixBackend
from phoenix_terminal.bridge.sanitize import public_agent, public_agent_tree, redact_log_line, redact_value
from phoenix_terminal.bridge.session_shim import (
    SerializedConnection,
    bridged_run_session,
)


class FakeEventBus:
    def __init__(self):
        self.listeners = {}

    def on(self, name, callback):
        self.listeners.setdefault(name, []).append(callback)

    def off(self, name, callback):
        self.listeners[name].remove(callback)

    def emit(self, name, **kwargs):
        for callback in self.listeners.get(name, []):
            callback(**kwargs)


class FakeStore:
    def __init__(self, deployments):
        self.deployments = deployments

    def get_dep(self, deployment_id):
        return self.deployments.get(deployment_id, {})


class FakeVault:
    def __init__(self):
        self.deployments = {
            "demo": {
                "label": "Demo",
                "private_key": "must-not-leak",
                "agents": [{
                    "universal_id": "watcher-1",
                    "name": "uptime_sentinel",
                    "connection": {"proto": "https", "channel": "outgoing.command", "host": "secret-host"},
                    "config": {"password": "must-not-leak"},
                }],
            }
        }

    def snapshot(self, name):
        return self.deployments if name == "deployments" else {}

    def get_store(self, name):
        assert name == "deployments"
        return FakeStore(self.deployments)


class FakeVaultCore:
    vault = FakeVault()

    @classmethod
    def get(cls):
        return cls.vault


class FakeConnection:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


class FakeProcess:
    @staticmethod
    def is_alive():
        return True


class CollisionDetectingConnection:
    def __init__(self):
        self._state_lock = threading.Lock()
        self.active_writers = 0
        self.max_active_writers = 0
        self.messages = []

    def send(self, message):
        with self._state_lock:
            self.active_writers += 1
            self.max_active_writers = max(self.max_active_writers, self.active_writers)
            if self.active_writers > 1:
                self.active_writers -= 1
                raise ValueError("concurrent send_bytes() calls are not supported")
        try:
            time.sleep(0.005)
            self.messages.append(message)
        finally:
            with self._state_lock:
                self.active_writers -= 1


class FakeCockpit:
    def __init__(self):
        self.connection = FakeConnection()
        self.session_processes = [{
            "session_id": "runtime-123",
            "deployment_id": "demo",
            "deployment_label": "Demo",
            "proc": FakeProcess(),
            "conn": self.connection,
        }]


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.events = FakeEventBus()
        self.cockpit = FakeCockpit()
        self.backend = PhoenixBackend(self.cockpit, self.events, FakeVaultCore)
        self.events.emit("vault.unlocked")

    def test_public_agent_excludes_host_and_config(self):
        agent = FakeVaultCore.vault.deployments["demo"]["agents"][0]
        public = public_agent(agent)
        self.assertNotIn("host", public)
        self.assertNotIn("config", public)
        self.assertEqual(public["universal_id"], "watcher-1")

    def test_recursive_and_log_redaction(self):
        self.assertEqual(redact_value({"password": "bad"}), {"password": "[REDACTED]"})
        line = 'password="bad" https://user:pass@example.com api_key=abc123'
        redacted = redact_log_line(line)
        self.assertNotIn("bad", redacted)
        self.assertNotIn("user:pass", redacted)
        self.assertNotIn("abc123", redacted)

    def test_log_redaction_covers_private_and_symmetric_key_labels(self):
        line = "MATRIX PRIVKEY: deadbeefcafe | SELF AES KEY: symmetric-secret"
        redacted = redact_log_line(line)
        self.assertNotIn("deadbeefcafe", redacted)
        self.assertNotIn("symmetric-secret", redacted)
        self.assertEqual(redacted.count("[REDACTED]"), 2)

    def test_live_tree_is_flattened_and_redacted(self):
        tree = {
            "universal_id": "matrix",
            "name": "matrix",
            "children": [{
                "universal_id": "watcher-1",
                "name": "uptime_sentinel",
                "connection": {"host": "private", "proto": "https"},
                "config": {"password": "private"},
            }],
        }
        public = public_agent_tree(tree)
        self.assertEqual([agent["universal_id"] for agent in public], ["matrix", "watcher-1"])
        self.assertNotIn("host", public[1])
        self.assertNotIn("config", public[1])

    def test_log_subscription_routes_only_identity_to_session(self):
        started = self.backend.start_agent_logs("Demo", "watcher-1", True)
        sent = self.cockpit.connection.messages[-1]
        self.assertEqual(sent["type"], "bridge.fetch_logs")
        self.assertEqual(sent["session_id"], "runtime-123")
        self.assertEqual(sent["agent_id"], "watcher-1")
        self.assertNotIn("connection", sent)
        self.assertNotIn("private_key", sent)
        self.assertEqual(started["state"], "starting")

    def test_vault_close_revokes_subscriptions(self):
        started = self.backend.start_agent_logs("demo", "watcher-1", True)
        self.events.emit("vault.closed")
        with self.assertRaises(ValueError):
            self.backend.read_agent_logs(started["subscription_id"], 0, 10)

    def test_disabling_bridge_revokes_subscriptions_without_closing_vault(self):
        started = self.backend.start_agent_logs("demo", "watcher-1", True)
        self.backend.disable_bridge()
        self.assertTrue(self.backend.vault_unlocked)
        with self.assertRaises(ValueError):
            self.backend.read_agent_logs(started["subscription_id"], 0, 10)

    def test_session_alias_resolves_to_runtime_session_for_agent_tree(self):
        refreshing = self.backend.agent_tree("Demo", True)
        self.assertEqual(refreshing["session_id"], "runtime-123")
        self.assertEqual(self.cockpit.connection.messages[-1], {
            "type": "bridge.agent_tree",
            "session_id": "runtime-123",
        })

        self.backend.handle_session_message({
            "type": "bridge.agent_tree",
            "session_id": "runtime-123",
            "agents": [{"universal_id": "watcher-1", "name": "uptime_sentinel"}],
        })
        ready = self.backend.agent_tree("demo", False)
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(ready["session_id"], "runtime-123")
        self.assertEqual(ready["agents"][0]["universal_id"], "watcher-1")

    def test_session_list_keeps_runtime_and_deployment_ids_distinct(self):
        session = self.backend.list_sessions()["sessions"][0]
        self.assertEqual(session["session_id"], "runtime-123")
        self.assertEqual(session["deployment_id"], "demo")

    def test_serialized_connection_prevents_concurrent_pipe_writes(self):
        raw = CollisionDetectingConnection()
        connection = SerializedConnection(raw)
        errors = []

        def writer(index):
            try:
                connection.send({"index": index})
            except Exception as exc:  # pragma: no cover - assertion reports thread failures
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(index,)) for index in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(raw.max_active_writers, 1)
        self.assertEqual(len(raw.messages), 12)

    def test_session_shim_accepts_phoenix_debug_flag(self):
        parameters = inspect.signature(bridged_run_session).parameters
        self.assertEqual(
            list(parameters),
            ["session_id", "conn", "debug_output"],
        )
        self.assertIs(parameters["debug_output"].default, False)

    def test_loopback_server_requires_token_and_removes_connection_file(self):
        with TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory)
            calls = []
            server = BridgeServer(lambda method, params: calls.append((method, params)) or {"state": "ok"}, data_dir)
            public_info = server.start()
            try:
                self.assertNotIn("token", public_info)
                connection = json.loads(server.connection_path.read_text(encoding="utf-8"))
                self.assertEqual(connection["host"], "127.0.0.1")
                request = Request(
                    f"http://127.0.0.1:{connection['port']}/rpc",
                    data=b'{"method":"bridge.status","params":{}}',
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(HTTPError) as rejected:
                    urlopen(request, timeout=2)
                self.assertEqual(rejected.exception.code, 401)
                self.assertEqual(calls, [])

                result = call_bridge(data_dir, "bridge.status", {})
                self.assertEqual(result, {"state": "ok"})
                self.assertEqual(calls, [("bridge.status", {})])
            finally:
                server.stop()
            self.assertFalse(server.connection_path.exists())

    def test_second_server_cannot_replace_an_active_bridge(self):
        with TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory)
            first = BridgeServer(lambda _method, _params: {"owner": "first"}, data_dir)
            second = BridgeServer(lambda _method, _params: {"owner": "second"}, data_dir)
            first.start()
            original_connection = first.connection_path.read_text(encoding="utf-8")
            try:
                with self.assertRaisesRegex(RuntimeError, "already enabled"):
                    second.start()
                self.assertEqual(first.connection_path.read_text(encoding="utf-8"), original_connection)
                self.assertEqual(call_bridge(data_dir, "bridge.status"), {"owner": "first"})
                second.stop()
                self.assertTrue(first.connection_path.exists())
            finally:
                first.stop()

    def test_stale_connection_file_is_replaced_when_bridge_is_enabled(self):
        with TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory)
            data_dir.joinpath("bridge.json").write_text('{"host":"127.0.0.1","port":0}', encoding="utf-8")
            server = BridgeServer(lambda _method, _params: {"state": "ok"}, data_dir)
            try:
                info = server.start()
                self.assertGreater(info["port"], 0)
                self.assertEqual(call_bridge(data_dir, "bridge.status"), {"state": "ok"})
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()
