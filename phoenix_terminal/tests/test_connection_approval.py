"""Synthetic-only checks for the independent Terminal approval presenter."""

import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel

from phoenix_terminal.connection_approval import (
    ApprovalResource,
    ConnectionApprovalRequest,
    PendingApprovalQueue,
)
from phoenix_terminal.connection_approval_dialog import ConnectionApprovalDialog


def request(request_id="request-1"):
    return ConnectionApprovalRequest(
        request_id=request_id,
        client_label="Synthetic monitor",
        vault_label="Synthetic test Vault",
        vault_revision="a" * 64,
        resources=(
            ApprovalResource("alpha-host-a", "Alpha on host A", ("alerts.read",)),
            ApprovalResource("alpha-host-b", "Alpha on host B"),
        ),
        operations=("alerts.read",),
        lifetime_seconds=900,
    )


class ApprovalContractTests(unittest.TestCase):
    def test_queue_is_bounded_deduplicated_and_reuse_cannot_widen_request(self):
        queue = PendingApprovalQueue(maximum=2)
        first = request()
        self.assertTrue(queue.enqueue(first))
        self.assertFalse(queue.enqueue(first))
        forged = ConnectionApprovalRequest(
            request_id=first.request_id,
            client_label="Different label",
            vault_label=first.vault_label,
            vault_revision=first.vault_revision,
            resources=first.resources,
            operations=first.operations,
            lifetime_seconds=first.lifetime_seconds,
        )
        with self.assertRaises(PermissionError):
            queue.enqueue(forged)
        queue.enqueue(request("request-2"))
        with self.assertRaises(RuntimeError):
            queue.enqueue(request("request-3"))

    def test_unknown_or_generic_operations_never_reach_dialog(self):
        for operation in ("alerts.delete", "panel.call", "packet.send", "*"):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                ConnectionApprovalRequest(
                    request_id="request",
                    client_label="Synthetic",
                    vault_label="Test",
                    vault_revision="b" * 64,
                    resources=(ApprovalResource("dep", "Deployment"),),
                    operations=(operation,),
                    lifetime_seconds=60,
                )

    def test_revoke_and_late_resolution_cannot_revive_request(self):
        queue = PendingApprovalQueue()
        queue.enqueue(request())
        decisions = queue.revoke_all()
        self.assertEqual(1, len(decisions))
        self.assertFalse(decisions[0].allowed)
        with self.assertRaises(PermissionError):
            queue.resolve("request-1", True, "late operator click")


class ApprovalDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = ConnectionApprovalDialog(request(), prompt_timeout_seconds=60)
        self.addCleanup(self.dialog.deleteLater)

    def test_deny_is_default_and_client_label_is_explicitly_unverified(self):
        self.dialog.show()
        self.app.processEvents()
        self.assertTrue(self.dialog.deny_button.isDefault())
        self.assertFalse(self.dialog.allow_button.isDefault())
        self.assertEqual(
            Qt.WindowModality.ApplicationModal,
            self.dialog.windowModality(),
        )
        self.assertTrue(
            bool(self.dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        )
        requester = self.dialog.findChild(QLabel, "TerminalApprovalRequester")
        self.assertIn("unverified client-supplied label", requester.text())

    def test_summon_makes_the_pending_decision_visible(self):
        self.dialog.summon()
        self.app.processEvents()
        self.assertTrue(self.dialog.isVisible())

    def test_dismissal_and_timeout_deny(self):
        self.dialog.reject()
        self.assertFalse(self.dialog.allowed)
        self.assertEqual("operator dismissed", self.dialog.decision_reason)
        timed = ConnectionApprovalDialog(request("request-2"), prompt_timeout_seconds=60)
        self.addCleanup(timed.deleteLater)
        timed._expire()
        self.assertFalse(timed.allowed)
        self.assertEqual("approval prompt timed out", timed.decision_reason)

    def test_operator_must_click_allow_for_positive_result(self):
        self.dialog._allow()
        self.assertTrue(self.dialog.allowed)
        self.assertEqual("operator approved", self.dialog.decision_reason)


if __name__ == "__main__":
    unittest.main()
