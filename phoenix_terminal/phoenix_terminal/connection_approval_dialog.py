"""Terminal-owned desktop presenter for a validated connection request."""

from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .connection_approval import ConnectionApprovalRequest


class ConnectionApprovalDialog(QDialog):
    """Display an immutable request; dismissal and timeout always deny it."""

    def __init__(
        self,
        request: ConnectionApprovalRequest,
        parent=None,
        *,
        prompt_timeout_seconds: int = 60,
    ):
        if not isinstance(request, ConnectionApprovalRequest):
            raise TypeError("request must be a validated ConnectionApprovalRequest")
        if type(prompt_timeout_seconds) is not int or not (
            1 <= prompt_timeout_seconds <= 300
        ):
            raise ValueError("Prompt timeout must be an integer from 1 to 300 seconds")
        super().__init__(parent)
        self.request = request
        self.allowed = False
        self.decision_reason = "dismissed"
        self.setWindowTitle("Allow Terminal connection?")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        # The request commonly arrives while the operator is typing in another
        # terminal.  On Windows, a newly executed child dialog can otherwise be
        # created behind its inactive owner and silently time out.  Keep only
        # this short-lived security prompt above other windows.
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(620, 480)

        layout = QVBoxLayout(self)
        heading = QLabel("Allow connection?")
        heading.setObjectName("TerminalApprovalHeading")
        heading.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(heading)

        requester = QLabel(
            f"Requesting client: {request.client_label} (unverified client-supplied label)"
        )
        requester.setObjectName("TerminalApprovalRequester")
        requester.setTextFormat(Qt.TextFormat.PlainText)
        requester.setWordWrap(True)
        layout.addWidget(requester)

        toolkit = QLabel(
            f"Toolkit: {request.vault_label}\n"
            f"Vault revision: {request.vault_revision[:12]}…\n"
            f"Access lifetime: {request.lifetime_seconds} seconds"
        )
        toolkit.setObjectName("TerminalApprovalToolkit")
        toolkit.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(toolkit)

        tree = QTreeWidget()
        tree.setObjectName("TerminalApprovalScope")
        tree.setHeaderLabels(("Prepared resources", "Effective operations", "Fixed destination"))
        tree.setRootIsDecorated(False)
        for resource in request.resources:
            operation_text = ", ".join(resource.operations) or "Connection only — no data operation"
            tree.addTopLevelItem(
                QTreeWidgetItem(
                    (f"{resource.label} [{resource.deployment_id}]", operation_text, resource.fixed_destination)
                )
            )
        layout.addWidget(tree)

        warning = QLabel(
            "The client receives no passwords, private keys, raw Vault data, "
            "editing authority, or operations not shown above. Railgun may launch only the saved "
            "deployment on its fixed server; an active universe is refused, never replaced."
        )
        warning.setObjectName("TerminalApprovalBoundary")
        warning.setTextFormat(Qt.TextFormat.PlainText)
        warning.setWordWrap(True)
        layout.addWidget(warning)

        buttons = QDialogButtonBox()
        self.deny_button = buttons.addButton(
            "Deny", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.allow_button = buttons.addButton(
            "Allow connection", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.deny_button.setObjectName("DenyTerminalConnection")
        self.allow_button.setObjectName("AllowTerminalConnection")
        self.deny_button.setDefault(True)
        self.deny_button.setAutoDefault(True)
        self.allow_button.setDefault(False)
        self.allow_button.setAutoDefault(False)
        buttons.rejected.connect(self._deny)
        buttons.accepted.connect(self._allow)
        layout.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._expire)
        self._timer.start(prompt_timeout_seconds * 1000)

    def summon(self):
        """Show the security decision prominently without changing its default."""
        self.show()
        self.raise_()
        self.activateWindow()
        QApplication.alert(self, 0)
        # Repeat after the native window exists; this is important on Windows
        # when focus was in the requesting PowerShell process.
        QTimer.singleShot(0, self.raise_)
        QTimer.singleShot(0, self.activateWindow)

    def _allow(self):
        self._timer.stop()
        self.allowed = True
        self.decision_reason = "operator approved"
        self.accept()

    def _deny(self):
        self._timer.stop()
        self.allowed = False
        self.decision_reason = "operator denied"
        self.reject()

    def _expire(self):
        self.allowed = False
        self.decision_reason = "approval prompt timed out"
        self.reject()

    def reject(self):
        self._timer.stop()
        self.allowed = False
        if self.decision_reason == "dismissed":
            self.decision_reason = "operator dismissed"
        super().reject()


def present_connection_approval(
    request: ConnectionApprovalRequest,
    *,
    parent=None,
    prompt_timeout_seconds: int = 60,
) -> bool:
    """Present one request on a desktop; never auto-approve headlessly."""
    app = QApplication.instance()
    if app is None:
        raise RuntimeError(
            "Terminal connection approval requires a desktop QApplication; "
            "headless approval is not available"
        )
    dialog = ConnectionApprovalDialog(
        request,
        parent,
        prompt_timeout_seconds=prompt_timeout_seconds,
    )
    try:
        dialog.summon()
        dialog.exec()
        return dialog.allowed is True
    finally:
        dialog.deleteLater()
