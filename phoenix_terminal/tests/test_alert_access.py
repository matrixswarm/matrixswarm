"""Synthetic alert-policy tests; no live server or production Vault."""

import unittest

from phoenix_terminal.alert_access import (
    TerminalAlertBuffer,
    public_alert,
    public_alert_page,
)
from phoenix_terminal.connection_approval import ApprovalResource
from phoenix_terminal.connection_broker import TerminalConnectionBroker, TerminalSnapshot


def snapshot():
    return TerminalSnapshot(
        vault_label="Synthetic Vault",
        vault_revision="d" * 64,
        resources=(
            ApprovalResource("allowed-deployment", "Allowed", ("alerts.read",)),
            ApprovalResource("denied-deployment", "Denied"),
        ),
        approval_lifetime_seconds=300,
    )


def request(secret="s" * 40):
    return {
        "request_id": "alert-request",
        "client_label": "Synthetic reader",
        "client_secret": secret,
    }


class AlertProjectionTests(unittest.TestCase):
    def test_projection_is_fixed_and_redacts_inline_and_named_secrets(self):
        alert = public_alert(
            {
                "content": {
                    "formatted_msg": "health failed token=do-not-return",
                    "origin": "harvester",
                    "level": "critical",
                    "private_key": "hidden",
                },
                "timestamp": "2026-10-01T00:00:00Z",
                "untrusted_extra": "discarded",
            }
        )
        self.assertEqual(
            {"timestamp", "level", "origin", "message", "event_type", "id"},
            set(alert),
        )
        self.assertEqual("CRITICAL", alert["level"])
        self.assertNotIn("do-not-return", repr(alert))
        self.assertNotIn("private_key", repr(alert))
        self.assertNotIn("untrusted_extra", repr(alert))

    def test_buffer_is_bounded_and_reports_cursor_gaps(self):
        alerts = TerminalAlertBuffer(capacity=2)
        alerts.append("allowed-deployment", [{"msg": "one"}, {"msg": "two"}])
        alerts.append("allowed-deployment", [{"msg": "three"}])
        page = alerts.read("allowed-deployment", 0, 100)
        self.assertTrue(page["gap"])
        self.assertEqual(1, page["oldest_cursor"])
        self.assertEqual(["two", "three"], [item["message"] for item in page["alerts"]])

    def test_adapter_page_cannot_add_fields_cross_scope_or_break_cursors(self):
        page = TerminalAlertBuffer().read("allowed-deployment", 0, 10)
        for forged in (
            {**page, "secret": "hidden"},
            {**page, "deployment_id": "denied-deployment"},
            {**page, "next_cursor": 99},
        ):
            with self.subTest(forged=forged), self.assertRaises(RuntimeError):
                public_alert_page("allowed-deployment", 0, 10, forged)


class AlertAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.alerts = TerminalAlertBuffer()
        self.alerts.append(
            "allowed-deployment",
            [{"content": {"msg": "Swarm healthy", "origin": "harvester"}}],
        )
        self.broker = TerminalConnectionBroker(
            snapshot(), operation_handlers={"alerts.read": self.alerts.read}
        )
        self.addCleanup(self.broker.close)
        self.broker.handle("connection.request", request())

    def _read(self, deployment_id="allowed-deployment", **changes):
        params = {
            "request_id": "alert-request",
            "client_secret": "s" * 40,
            "deployment_id": deployment_id,
            "after": 0,
            "limit": 100,
        }
        params.update(changes)
        return self.broker.handle("alerts.read", params)

    def test_no_approval_no_alerts_and_no_scope_leak(self):
        with self.assertRaisesRegex(PermissionError, "not approved"):
            self._read()
        self.broker.resolve("alert-request", True, "operator approved")
        result = self._read()
        self.assertEqual("Swarm healthy", result["alerts"][0]["message"])
        self.assertEqual(
            ["alerts.read"],
            self.broker.handle(
                "connection.status",
                {"request_id": "alert-request", "client_secret": "s" * 40},
            )["operations_available"],
        )
        with self.assertRaisesRegex(PermissionError, "not allowed"):
            self._read("denied-deployment")
        with self.assertRaises(PermissionError):
            self.broker.handle("alerts.delete", {})

    def test_unknown_fields_and_bad_pagination_fail_before_adapter(self):
        self.broker.resolve("alert-request", True, "operator approved")
        with self.assertRaises(ValueError):
            self._read(approve=True)
        for changes in ({"after": -1}, {"limit": 0}, {"limit": 201}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self._read(**changes)

    def test_snapshot_cannot_advertise_operation_without_adapter(self):
        with self.assertRaisesRegex(ValueError, "without a live adapter"):
            TerminalConnectionBroker(snapshot())

    def test_broker_reprojects_a_buggy_adapter_response(self):
        def buggy_reader(deployment_id, after, limit):
            return {
                "deployment_id": deployment_id,
                "alerts": [{"msg": "token=hidden-value", "extra": "discard"}],
                "next_cursor": 1,
                "oldest_cursor": 0,
                "end_cursor": 1,
                "gap": False,
            }

        broker = TerminalConnectionBroker(
            snapshot(), operation_handlers={"alerts.read": buggy_reader}
        )
        self.addCleanup(broker.close)
        broker.handle("connection.request", request())
        broker.resolve("alert-request", True, "operator approved")
        result = broker.handle(
            "alerts.read",
            {
                "request_id": "alert-request",
                "client_secret": "s" * 40,
                "deployment_id": "allowed-deployment",
                "after": 0,
                "limit": 10,
            },
        )
        self.assertNotIn("hidden-value", repr(result))
        self.assertNotIn("extra", repr(result))


if __name__ == "__main__":
    unittest.main()
