from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QFileDialog
)
from matrix_gui.util.resolve_matrixswarm_base import resolve_matrixswarm_base
from .vault_service import VaultService
from .yubikey_worker import YubiKeyCredentialWorker

class VaultCreateDialog(QDialog):
    """Creates a new vault and returns {vault_path, password}."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Vault")
        self.setMinimumSize(430, 270)

        self.vault_path = None
        self.vault_password = None
        self.vault_auth_method = "password"
        self._yubikey_worker = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Enter a password or YubiKey secondary word:"))

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Vault Password or Secondary Word")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.password_input)

        self.create_btn = QPushButton("🛠 Create Vault")
        self.yubikey_btn = QPushButton("🔑 Create with YubiKey (Slot 2)")
        self.yubikey_btn.setToolTip(
            "Uses a preconfigured HMAC-SHA1 challenge-response slot. "
            "Phoenix never changes the YubiKey configuration."
        )
        self.cancel_btn = QPushButton("❌ Cancel")

        self.create_btn.clicked.connect(self._create)
        self.yubikey_btn.clicked.connect(self._create_with_yubikey)
        self.cancel_btn.clicked.connect(self.reject)

        layout.addWidget(self.create_btn)
        layout.addWidget(self.yubikey_btn)

        self.yubikey_status = QLabel(
            "YubiKey mode expects HMAC-SHA1 slot 2 with touch required."
        )
        self.yubikey_status.setWordWrap(True)
        self.yubikey_status.setStyleSheet("color: #8fd; font-size: 11px;")
        layout.addWidget(self.yubikey_status)
        layout.addWidget(self.cancel_btn)

    def _create(self):
        pw = self.password_input.text().strip()
        if not pw:
            QMessageBox.warning(self, "Invalid Password", "Password cannot be empty.")
            return

        self._save_with_password(pw)

    def _create_with_yubikey(self):
        secondary_word = self.password_input.text().strip()
        if not secondary_word:
            QMessageBox.warning(
                self,
                "Missing Secondary Word",
                "Enter the YubiKey secondary word.",
            )
            return

        self._set_yubikey_busy(True, "Contacting YubiKey slot 2…")
        worker = YubiKeyCredentialWorker(secondary_word, self)
        self.password_input.clear()
        self._yubikey_worker = worker
        worker.touch_requested.connect(
            lambda: self.yubikey_status.setText("Touch the YubiKey now…")
        )
        worker.credential_ready.connect(self._on_yubikey_ready)
        worker.failed.connect(self._on_yubikey_failed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_yubikey_ready(self, password, serial):
        self._set_yubikey_busy(False, "YubiKey response accepted.")
        self._yubikey_worker = None
        self._save_with_password(password, auth_method="yubikey")

    def _on_yubikey_failed(self, message):
        self._set_yubikey_busy(False, "")
        self._yubikey_worker = None
        QMessageBox.warning(self, "YubiKey", message)

    def _set_yubikey_busy(self, busy, status):
        self.password_input.setEnabled(not busy)
        self.create_btn.setEnabled(not busy)
        self.yubikey_btn.setEnabled(not busy)
        self.yubikey_status.setText(status)

    def _save_with_password(self, password, auth_method="password"):

        vault_dir = resolve_matrixswarm_base() / "vaults"
        vault_dir.mkdir(parents=True, exist_ok=True)

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save New Vault As",
            str(vault_dir),
            "Vault Files (*.json)"
        )
        if not path:
            return

        if not path.endswith(".json"):
            path += ".json"

        initial_data = {
            # REQUIRED BY STORE SYSTEM
            "deployments": {},
            "workspaces": {},
            "registry": {},
        }

        try:
            VaultService.save_vault(path, initial_data, password)
        except Exception as e:
            QMessageBox.critical(self, "Vault Error", f"Failed to create vault:\n{e}")
            return

        self.vault_path = path
        self.vault_password = password
        self.vault_auth_method = auth_method
        self.accept()

    def reject(self):
        if self._yubikey_worker and self._yubikey_worker.isRunning():
            self._yubikey_worker.cancel()
        super().reject()
