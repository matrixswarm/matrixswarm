"""Synthetic-only fixed-target tests. No production credentials or SSH dispatch."""
import base64
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "phoenix"))
from phoenix_terminal.cli import build_parser
from phoenix_terminal.connection_approval import ApprovalResource
from phoenix_terminal.connection_broker import TerminalConnectionBroker, TerminalSnapshot
from phoenix_terminal.remote_access import RemoteOperations, public_inventory_page, target_from_vault
from phoenix_terminal.terminal_runtime import load_live_toolkit
from phoenix_terminal.mcp_server import TerminalMcpAdapter
from phoenix_terminal.terminal_server import TerminalRequestServer
from phoenix_terminal.terminal_client import TerminalClientIdentity


def fixture():
    pin = "SHA256:" + base64.b64encode(b"x" * 32).decode().rstrip("=")
    deployment = {"label": "Synthetic", "universe": "test", "linux_user": "matrix-test", "agents": [],
        "ssh_serial": "ssh-a", "railgun_target_identity": {"host": "a.invalid", "port": 22, "pin": pin},
        "railgun_boot_options": {"reboot": True, "clean": True, "protect_memory": True},
        "encrypted_bundle": {k: "eA==" for k in ("nonce", "tag", "ciphertext")},
        "swarm_key": base64.b64encode(b"SYNTHETIC-NOT-REAL-SECRET-KEY-1234").decode()}
    return {"deployments": {"allowed": deployment, "excluded": deepcopy(deployment)},
        "registry": {"ssh": {"ssh-a": {"host": "a.invalid", "port": 22, "username": "root",
            "auth_type": "password", "password": "SYNTHETIC-HIDDEN", "trusted_host_fingerprint": pin}}},
        "terminal_access": {"schema_version": 1, "enabled": True, "approval_lifetime_seconds": 60,
            "permissions": {op: {"enabled": True, "deployment_ids": ["allowed"]}
                for op in ("swarms.list", "railgun.launch")}}}


def inventory(deployment_id="allowed"):
    return {"deployment_id": deployment_id, "universes": [{"universe": "test", "status": "active",
        "agent_count": 2, "rss_bytes": 100, "cpu_percent": 0.2, "secret": "DO-NOT-EXPORT"}]}


class TargetTests(unittest.TestCase):
    def test_exact_binding_detached_secrets_and_no_reboot_or_clean_authority(self):
        data = fixture()
        target = target_from_vault(data, "allowed", "a" * 64, launch=True)
        self.assertNotIn("SYNTHETIC", repr(target))
        options = json.loads(target.launch_json)
        self.assertEqual(["--protect-memory"], options["boot_flags"])
        self.assertTrue(options["require_inactive"])
        data["registry"]["ssh"]["ssh-a"]["host"] = "other.invalid"
        self.assertEqual("a.invalid", json.loads(target.profile_json)["host"])
        with self.assertRaisesRegex(ValueError, "binding changed"):
            target_from_vault(data, "allowed", "a" * 64)

    def test_changed_port_pin_profile_missing_credentials_and_agent_auth_fail_closed(self):
        for change in (lambda d: d["deployments"]["allowed"].update(ssh_serial="missing"),
                       lambda d: d["registry"]["ssh"]["ssh-a"].update(port=23),
                       lambda d: d["registry"]["ssh"]["ssh-a"].update(trusted_host_fingerprint="SHA256:" + "y" * 43),
                       lambda d: d["registry"]["ssh"]["ssh-a"].update(password=""),
                       lambda d: d["registry"]["ssh"]["ssh-a"].update(auth_type="agent")):
            data = fixture()
            change(data)
            with self.assertRaises(ValueError):
                target_from_vault(data, "allowed", "a" * 64, launch=True)

    def test_live_toolkit_has_only_permitted_targets_and_never_connects(self):
        data = fixture()
        with patch("phoenix_terminal.terminal_runtime.load_vault_data", return_value=deepcopy(data)), \
             patch("matrix_gui.modules.railgun.ssh_support.connect_ssh_profile") as connect:
            view, targets = load_live_toolkit(ROOT / "phoenix", "synthetic.json", "not-a-password")
        self.assertEqual({}, targets)
        self.assertEqual({"allowed"}, set(targets.remote_targets))
        self.assertEqual((), view.resources[1].operations)
        self.assertIn("a.invalid", view.resources[0].fixed_destination)
        self.assertNotIn("SYNTHETIC-HIDDEN", repr(view))
        connect.assert_not_called()

    def test_projection_strips_credentials_and_rejects_nonfinite_or_foreign_response(self):
        self.assertNotIn("secret", repr(public_inventory_page("allowed", inventory())))
        bad = inventory()
        bad["universes"][0]["cpu_percent"] = float("nan")
        with self.assertRaises(ValueError):
            public_inventory_page("allowed", bad)
        with self.assertRaises(ValueError):
            public_inventory_page("excluded", inventory())

    def test_sealed_hash_and_contradictory_saved_options_fail_before_advertising(self):
        data = fixture()
        data["deployments"]["allowed"]["encrypted_hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash did not match"):
            target_from_vault(data, "allowed", "a" * 64, launch=True)
        data = fixture()
        data["deployments"]["allowed"]["railgun_boot_options"]["universe"] = "other"
        with self.assertRaisesRegex(ValueError, "do not match"):
            target_from_vault(data, "allowed", "a" * 64, launch=True)


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.now = [10.0]
        self.reader = Mock(return_value=inventory())
        self.launcher = Mock(return_value={"deployment_id": "allowed", "operation_id": "b" * 32,
            "remote_request_id": "c" * 64, "state": "queued", "secret": "DO-NOT-EXPORT"})
        self.broker = TerminalConnectionBroker(TerminalSnapshot("fixture", "a" * 64,
            (ApprovalResource("allowed", "Allowed", ("swarms.list", "railgun.launch")),
             ApprovalResource("excluded", "Excluded")), 60), clock=lambda: self.now[0],
            operation_handlers={"swarms.list": self.reader, "railgun.launch": self.launcher,
                                "railgun.status": self.launcher})
        self.auth = {"request_id": "client", "client_secret": "x" * 32}
        self.broker.handle("connection.request", {**self.auth, "client_label": "Unverified"})
        self.params = {**self.auth, "deployment_id": "allowed"}
        self.addCleanup(self.broker.close)

    def test_pending_and_excluded_never_dispatch(self):
        with self.assertRaises(PermissionError):
            self.broker.handle("swarms.list", self.params)
        self.broker.resolve("client", True, "operator")
        for method in ("swarms.list", "railgun.launch", "railgun.status"):
            params = {**self.params, "deployment_id": "excluded"}
            if method.startswith("railgun"):
                params["operation_id"] = "b" * 32
            with self.assertRaises(PermissionError):
                self.broker.handle(method, params)
        self.reader.assert_not_called()
        self.launcher.assert_not_called()

    def test_smuggled_targets_invalid_ids_and_generic_mutations_never_dispatch(self):
        self.broker.resolve("client", True, "operator")
        for field in ("host", "username", "universe", "command", "boot_flags", "pin", "replace"):
            with self.assertRaises(ValueError):
                self.broker.handle("railgun.launch", {**self.params, "operation_id": "b" * 32, field: "override"})
        for method in ("swarms.kill", "railgun.restart", "shell", "packet.send"):
            with self.assertRaises(PermissionError):
                self.broker.handle(method, self.params)
        for value in (True, "new", "B" * 32):
            with self.assertRaises(ValueError):
                self.broker.handle("railgun.launch", {**self.params, "operation_id": value})
        self.launcher.assert_not_called()

    def test_inventory_and_receipts_are_reprojected_and_bound_to_owner(self):
        self.broker.resolve("client", True, "operator")
        self.assertNotIn("DO-NOT-EXPORT", repr(self.broker.handle("swarms.list", self.params)))
        value = self.broker.handle("railgun.launch", {**self.params, "operation_id": "b" * 32})
        self.assertNotIn("secret", value)
        self.assertEqual("client", self.launcher.call_args.args[2])

    def test_revocation_during_remote_read_does_not_deadlock_or_release_result(self):
        self.broker.resolve("client", True, "operator")
        def read(dep, lease):
            worker = threading.Thread(target=self.broker.close)
            worker.start()
            worker.join(1)
            self.assertFalse(worker.is_alive(), "Lifecycle lock was held over network")
            self.assertFalse(lease())
            return inventory(dep)
        self.reader.side_effect = read
        with self.assertRaises(PermissionError):
            self.broker.handle("swarms.list", self.params)

    def test_expiry_and_raw_adapter_errors_are_not_exported(self):
        self.broker.resolve("client", True, "operator")
        self.reader.side_effect = ValueError("SYNTHETIC-HIDDEN")
        with self.assertRaises(RuntimeError) as failure:
            self.broker.handle("swarms.list", self.params)
        self.assertNotIn("SYNTHETIC-HIDDEN", str(failure.exception))
        self.now[0] += 61
        with self.assertRaises(PermissionError):
            self.broker.handle("swarms.list", self.params)


class WorkerTests(unittest.TestCase):
    def test_verified_completion_and_active_refusal_are_receipts_not_health(self):
        target = target_from_vault(fixture(), "allowed", "a" * 64, launch=True)
        target = replace(target, connector=Mock(return_value=(Mock(), "pin")))
        for code, expected in ((0, "completed"), (73, "refused_active"), (9, "failed")):
            with self.subTest(code=code):
                def exchange(client, command, check, **kwargs):
                    kwargs["on_dispatch"]()
                    remote_id = command.split("--request-id ")[1].split()[0]
                    return code, f"[RAILGUN][COMPLETED] request={remote_id} exit={code}\n".encode(), b""
                remote = RemoteOperations({"allowed": target})
                with patch("phoenix_terminal.remote_access._exchange", side_effect=exchange):
                    remote.launch("allowed", "b" * 32, "client", lambda: True)
                    deadline = time.monotonic() + 2
                    while True:
                        status = remote.status("allowed", "b" * 32, "client", lambda: True)
                        if status["state"] not in {"queued", "running"}:
                            break
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.01)
                    self.assertEqual(expected, status["state"])
                    self.assertFalse(status["live_health_verified"])
                remote.close()

    def test_same_id_is_queued_once_owner_isolation_unknown_and_runtime_retry_identity(self):
        target = target_from_vault(fixture(), "allowed", "a" * 64, launch=True)
        connector = Mock(return_value=(Mock(), "pin"))
        target = replace(target, connector=connector)
        gate = threading.Event()
        def exchange(*args, **kwargs):
            kwargs["on_dispatch"]()
            gate.wait(2)
            raise ConnectionError("SYNTHETIC-HIDDEN")
        with patch("phoenix_terminal.remote_access._exchange", side_effect=exchange):
            remote = RemoteOperations({"allowed": target})
            first = remote.launch("allowed", "b" * 32, "client-a", lambda: True)
            second = remote.launch("allowed", "b" * 32, "client-a", lambda: True)
            self.assertEqual(first["remote_request_id"], second["remote_request_id"])
            with self.assertRaises(ValueError):
                remote.status("allowed", "b" * 32, "client-b", lambda: True)
            gate.set()
            deadline = time.monotonic() + 2
            while remote.status("allowed", "b" * 32, "client-a", lambda: True)["state"] in {"queued", "running"}:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
            self.assertEqual("outcome_unknown", remote.status("allowed", "b" * 32, "client-a", lambda: True)["state"])
            connector.assert_called_once()
            remote.close()
            reopened = RemoteOperations({"allowed": target})
            retry = reopened.launch("allowed", "b" * 32, "new-client", lambda: True)
            self.assertEqual(first["remote_request_id"], retry["remote_request_id"])
            reopened.close()

    def test_no_lease_never_connects(self):
        target = target_from_vault(fixture(), "allowed", "a" * 64, launch=True)
        connect = Mock()
        remote = RemoteOperations({"allowed": replace(target, connector=connect)})
        self.addCleanup(remote.close)
        with self.assertRaises(PermissionError):
            remote.launch("allowed", "b" * 32, "owner", lambda: False)
        connect.assert_not_called()

    def test_cli_and_mcp_use_exact_client_operations(self):
        parsed = build_parser().parse_args(["terminal", "railgun", "launch", "allowed", "--operation-id", "b" * 32])
        self.assertEqual("launch", parsed.railgun_command)
        identity = Mock()
        adapter = TerminalMcpAdapter(Path("synthetic-only"), identity=identity)
        adapter.swarms("allowed")
        adapter.launch("allowed", "b" * 32)
        adapter.launch_status("allowed", "b" * 32)
        identity.list_swarms.assert_called_once_with("allowed")
        identity.launch_railgun.assert_called_once_with("allowed", "b" * 32)
        identity.railgun_status.assert_called_once_with("allowed", "b" * 32)


class LoopbackSshTests(unittest.TestCase):
    def test_pinned_ssh_and_loopback_client_inventory_refusal_and_disconnect(self):
        """Actual SSH framing + host pin + CLI transport; no remote shell executes."""
        import paramiko
        import tempfile
        from matrix_gui.modules.railgun.ssh_support import sha256_fingerprint
        from matrix_gui.modules.swarms.remote import LIST_COMMAND
        host_key = paramiko.RSAKey.generate(2048)
        calls, failures = [], []
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(5)
        listener.settimeout(0.1)
        stop = threading.Event()

        class Server(paramiko.ServerInterface):
            def check_auth_password(self, username, password):
                return paramiko.AUTH_SUCCESSFUL if username == "fixture" and password == "SYNTHETIC-ONLY" else paramiko.AUTH_FAILED
            def get_allowed_auths(self, username):
                return "password"
            def check_channel_request(self, kind, channel_id):
                return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
            def check_channel_exec_request(self, channel, command):
                self.command = command.decode()
                return True

        def serve():
            while not stop.is_set():
                try:
                    peer, _ = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                transport = paramiko.Transport(peer)
                try:
                    transport.add_server_key(host_key)
                    server = Server()
                    transport.start_server(server=server)
                    channel = transport.accept(5)
                    deadline = time.monotonic() + 5
                    while not hasattr(server, "command"):
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Fixture exec not received")
                        time.sleep(0.01)
                    calls.append(server.command)
                    if server.command == LIST_COMMAND:
                        channel.sendall(json.dumps({"version": 1, "universes": inventory()["universes"]}).encode())
                        channel.send_exit_status(0)
                    else:
                        # Accept ONLY the guarded fixed-target request built by
                        # the adapter; consume envelope but execute NOTHING.
                        self.assertIn("--require-inactive", server.command)
                        self.assertIn("--inactive-protocol", server.command)
                        body = bytearray()
                        while True:
                            chunk = channel.recv(32768)
                            if not chunk:
                                break
                            body.extend(chunk)
                        self.assertEqual(1, json.loads(body)["version"])
                        remote_id = server.command.split("--request-id ")[1].split()[0]
                        channel.sendall(f"[RAILGUN][COMPLETED] request={remote_id} exit=73\n".encode())
                        channel.send_exit_status(73)
                    channel.shutdown_write()
                    # Keep the SSH transport alive until the client consumes
                    # the response and closes it. A fixed 50 ms sleep can race
                    # the exec acknowledgement/data delivery on Linux and reset
                    # the connection before the inventory reaches the client.
                    deadline = time.monotonic() + 5
                    while transport.is_active() and not stop.is_set():
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Fixture client did not disconnect")
                        time.sleep(0.01)
                except Exception as error:
                    failures.append(type(error).__name__)
                finally:
                    transport.close()

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        try:
            data = fixture()
            profile = data["registry"]["ssh"]["ssh-a"]
            profile.update(host="127.0.0.1", port=listener.getsockname()[1], username="fixture",
                           password="SYNTHETIC-ONLY", trusted_host_fingerprint=sha256_fingerprint(host_key))
            data["deployments"]["allowed"]["railgun_target_identity"] = {
                "host": profile["host"], "port": profile["port"], "pin": profile["trusted_host_fingerprint"]}
            target = target_from_vault(data, "allowed", "a" * 64, launch=True)
            remote = RemoteOperations({"allowed": target})
            broker = TerminalConnectionBroker(TerminalSnapshot("Fixture", "a" * 64,
                (ApprovalResource("allowed", "Fixture", ("swarms.list", "railgun.launch")),), 60),
                operation_handlers={"swarms.list": remote.inventory, "railgun.launch": remote.launch,
                                    "railgun.status": remote.status})
            with tempfile.TemporaryDirectory() as directory:
                endpoint = TerminalRequestServer(broker.handle, Path(directory))
                endpoint.start()
                try:
                    identity = TerminalClientIdentity(directory)
                    pending = identity.request("synthetic client")
                    with self.assertRaises(RuntimeError):
                        identity.list_swarms("allowed")
                    self.assertEqual([], calls)
                    broker.resolve(pending["request_id"], True, "fixture operator")
                    page = identity.list_swarms("allowed")
                    self.assertEqual("test", page["universes"][0]["universe"])
                    self.assertNotIn("DO-NOT-EXPORT", repr(page))
                    identity.launch_railgun("allowed", "b" * 32)
                    deadline = time.monotonic() + 5
                    while True:
                        status = identity.railgun_status("allowed", "b" * 32)
                        if status["state"] not in {"queued", "running"}:
                            break
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.01)
                    self.assertEqual("refused_active", status["state"])
                    identity.launch_railgun("allowed", "b" * 32)
                    self.assertEqual(2, len(calls))  # inventory + one launch only
                    identity.disconnect()
                    with self.assertRaises(RuntimeError):
                        identity.list_swarms("allowed")
                finally:
                    broker.close()
                    remote.close()
                    endpoint.stop()
            self.assertEqual([], failures)
        finally:
            stop.set()
            listener.close()
            worker.join(2)


if __name__ == "__main__":
    unittest.main()
