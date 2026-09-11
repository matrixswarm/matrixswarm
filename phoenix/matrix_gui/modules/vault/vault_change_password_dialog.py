from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QLineEdit,
    QMessageBox, QFileDialog, QCheckBox
)
from .vault_service import VaultService
from .yubikey_worker import YubiKeyCredentialWorker
from matrix_gui.util.resolve_matrixswarm_base import resolve_matrixswarm_base

class VaultChangePasswordDialog(QDialog):
    """Allows user to change password of an existing vault."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change Vault Password")
        self.setMinimumSize(440, 350)

        self.vault_path = None
        self._yubikey_worker = None
        self._pending_credentials = None
        self._pending_factors = []

        layout = QVBoxLayout(self)

        self.select_btn = QPushButton("📂 Select Vault")
        self.select_btn.clicked.connect(self._choose_file)
        layout.addWidget(self.select_btn)

        self.old_pw = QLineEdit()
        self.old_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.old_pw.setPlaceholderText("Current Password or Secondary Word")
        layout.addWidget(self.old_pw)

        self.old_uses_yubikey = QCheckBox("Current credential uses YubiKey")
        layout.addWidget(self.old_uses_yubikey)

        self.new_pw = QLineEdit()
        self.new_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pw.setPlaceholderText("New Password or Secondary Word")
        layout.addWidget(self.new_pw)

        self.new_uses_yubikey = QCheckBox("Protect new credential with YubiKey")
        self.new_uses_yubikey.setToolTip(
            "Uses preconfigured HMAC-SHA1 challenge-response slot 2. "
            "Phoenix never changes the YubiKey configuration."
        )
        layout.addWidget(self.new_uses_yubikey)

        self.change_btn = QPushButton("🔑 Change Password")
        self.change_btn.clicked.connect(self._change)
        self.change_btn.setDefault(True)
        layout.addWidget(self.change_btn)

        self.yubikey_status = QLabel(
            "YubiKey mode expects HMAC-SHA1 slot 2 with touch required."
        )
        self.yubikey_status.setWordWrap(True)
        self.yubikey_status.setStyleSheet("color: #8fd; font-size: 11px;")
        layout.addWidget(self.yubikey_status)

        self.cancel_btn = QPushButton("❌ Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self.cancel_btn)

        self.result_data = None
        self.result_password = None

    def _choose_file(self):
        vault_dir = resolve_matrixswarm_base() / "vaults"
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Vault", str(vault_dir), "Vault Files (*.json)"
        )
        if path:
            self.vault_path = path

    def _change(self):
        if not self.vault_path:
            QMessageBox.warning(self, "Missing File", "Select a vault first.")
            return

        old_pw = self.old_pw.text().strip()
        new_pw = self.new_pw.text().strip()

        if not old_pw or not new_pw:
            QMessageBox.warning(self, "Missing Password", "Fill both fields.")
            return

        self._pending_credentials = {"old": old_pw, "new": new_pw}
        self.old_pw.clear()
        self.new_pw.clear()
        self._pending_factors = []
        if self.old_uses_yubikey.isChecked():
            self._pending_factors.append("old")
        if self.new_uses_yubikey.isChecked():
            self._pending_factors.append("new")

        if self._pending_factors:
            self._set_yubikey_busy(True)
            self._derive_next_yubikey_credential()
            return

        self._finish_change()

    def _derive_next_yubikey_credential(self):
        factor = self._pending_factors[0]
        label = "current" if factor == "old" else "new"
        self.yubikey_status.setText(
            f"Contacting YubiKey slot 2 for the {label} credential…"
        )
        worker = YubiKeyCredentialWorker(
            self._pending_credentials[factor],
            self,
        )
        worker.factor = factor
        self._yubikey_worker = worker
        worker.touch_requested.connect(
            lambda: self.yubikey_status.setText(
                f"Touch the YubiKey for the {label} credential…"
            )
        )
        worker.credential_ready.connect(self._on_yubikey_ready)
        worker.failed.connect(self._on_yubikey_failed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_yubikey_ready(self, password, serial):
        factor = self._pending_factors.pop(0)
        self._pending_credentials[factor] = password
        self._yubikey_worker = None
        if self._pending_factors:
            self._derive_next_yubikey_credential()
            return
        self.yubikey_status.setText("YubiKey response accepted.")
        self._set_yubikey_busy(False, keep_status=True)
        self._finish_change()

    def _on_yubikey_failed(self, message):
        self._pending_credentials = None
        self._pending_factors = []
        self._yubikey_worker = None
        self._set_yubikey_busy(False)
        QMessageBox.warning(self, "YubiKey", message)

    def _finish_change(self):
        old_password = self._pending_credentials["old"]
        new_password = self._pending_credentials["new"]
        try:
            data = VaultService.change_password(
                self.vault_path,
                old_password,
                new_password,
            )
        except Exception:
            QMessageBox.critical(
                self,
                "Error",
                "The current password or YubiKey credential is incorrect.",
            )
            self._pending_credentials = None
            return

        self.result_data = data
        self.result_password = new_password
        self._pending_credentials = None
        QMessageBox.information(self, "Success", "Password updated.")
        self.accept()

    def _set_yubikey_busy(self, busy, keep_status=False):
        for widget in (
            self.select_btn,
            self.old_pw,
            self.old_uses_yubikey,
            self.new_pw,
            self.new_uses_yubikey,
            self.change_btn,
        ):
            widget.setEnabled(not busy)
        if not busy and not keep_status:
            self.yubikey_status.setText("")

    def reject(self):
        if self._yubikey_worker and self._yubikey_worker.isRunning():
            self._yubikey_worker.cancel()
        super().reject()
