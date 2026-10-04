"""Connection lifecycle tests; synthetic snapshots and loopback only."""

from pathlib import Path
import tempfile
import unittest

from phoenix_terminal.connection_approval import ApprovalResource
from phoenix_terminal.connection_broker import TerminalConnectionBroker, TerminalSnapshot
from phoenix_terminal.terminal_client import TerminalClientIdentity, call_terminal
from phoenix_terminal.terminal_server import TerminalRequestServer


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def snapshot(lifetime=60):
    return TerminalSnapshot(
        vault_label="Synthetic Vault",
        vault_revision="c" * 64,
        resources=(
            ApprovalResource("same-name-host-a", "Same Name A"),
            ApprovalResource("same-name-host-b", "Same Name B"),
        ),
        approval_lifetime_seconds=lifetime,
    )


def request_params(request_id="request-1", secret="s" * 40, label="Synthetic client"):
    return {"request_id": request_id, "client_label": label, "client_secret": secret}


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.broker = TerminalConnectionBroker(snapshot(), clock=self.clock)
        self.addCleanup(self.broker.close)

    def test_request_releases_no_resources_and_client_cannot_approve(self):
        result = self.broker.handle("connection.request", request_params())
        self.assertEqual("pending", result["state"])
        self.assertEqual([], result["operations_available"])
        rendered = repr(result)
        self.assertNotIn("same-name", rendered)
        self.assertNotIn("Synthetic Vault", rendered)
        for method in ("connection.approve", "deployment.list", "alerts.read", "vault.read"):
            with self.subTest(method=method), self.assertRaises(PermissionError):
                self.broker.handle(method, {})

    def test_approval_binds_exact_request_secret_revision_and_lifetime(self):
        self.broker.handle("connection.request", request_params())
        pending = self.broker.next_approval()
        self.assertEqual("c" * 64, pending.vault_revision)
        self.assertEqual(
            ["same-name-host-a", "same-name-host-b"],
            [item.deployment_id for item in pending.resources],
        )
        self.broker.resolve("request-1", True, "operator approved")
        status = self.broker.handle(
            "connection.status",
            {"request_id": "request-1", "client_secret": "s" * 40},
        )
        self.assertEqual("approved", status["state"])
        self.assertEqual(60, status["remaining_seconds"])
        with self.assertRaises(PermissionError):
            self.broker.handle(
                "connection.status",
                {"request_id": "request-1", "client_secret": "x" * 40},
            )
        self.clock.now = 161
        self.assertEqual(
            "expired",
            self.broker.handle(
                "connection.status",
                {"request_id": "request-1", "client_secret": "s" * 40},
            )["state"],
        )

    def test_duplicate_is_idempotent_but_rebinding_is_rejected(self):
        self.broker.handle("connection.request", request_params())
        self.assertEqual(
            "pending", self.broker.handle("connection.request", request_params())["state"]
        )
        with self.assertRaises(PermissionError):
            self.broker.handle(
                "connection.request", request_params(secret="x" * 40)
            )
        with self.assertRaises(PermissionError):
            self.broker.handle(
                "connection.request", request_params(label="Different")
            )
        self.assertEqual(1, len(self.broker.queue))

    def test_denial_disconnect_and_lock_cannot_be_revived(self):
        self.broker.handle("connection.request", request_params())
        self.broker.resolve("request-1", False, "operator denied")
        self.assertEqual(
            "denied",
            self.broker.handle(
                "connection.status",
                {"request_id": "request-1", "client_secret": "s" * 40},
            )["state"],
        )
        with self.assertRaises(PermissionError):
            self.broker.resolve("request-1", True, "late click")
        self.broker.close()
        with self.assertRaises(PermissionError):
            self.broker.handle("terminal.status", {})

    def test_parameter_smuggling_is_rejected(self):
        params = request_params()
        params["approve"] = True
        with self.assertRaises(ValueError):
            self.broker.handle("connection.request", params)


class LoopbackTests(unittest.TestCase):
    def test_real_loopback_request_approval_status_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            broker = TerminalConnectionBroker(snapshot())
            server = TerminalRequestServer(broker.handle, directory)
            identity = TerminalClientIdentity(directory)
            try:
                server.start()
                self.assertTrue((directory / "terminal-access.json").is_file())
                result = identity.request("Synthetic local client")
                self.assertEqual("pending", result["state"])
                broker.resolve(broker.next_approval().request_id, True, "operator approved")
                self.assertEqual("approved", identity.status()["state"])
                endpoint = call_terminal(directory, "terminal.status", {})
                self.assertEqual(1, endpoint["active_connections"])
                self.assertEqual([], endpoint["operations_available"])
                self.assertEqual("revoked", identity.disconnect()["state"])
                self.assertFalse(identity.path.exists())
            finally:
                broker.close()
                server.stop()
            self.assertFalse((directory / "terminal-access.json").exists())


if __name__ == "__main__":
    unittest.main()
