from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QMessageBox, QFileDialog, QCheckBox
)
from PyQt6.QtCore import Qt
from .vault_service import VaultService
from .yubikey_worker import YubiKeyCredentialWorker
from matrix_gui.util.resolve_matrixswarm_base import resolve_matrixswarm_base

class VaultUnlockDialog(QDialog):
    """Unlocks an existing vault and returns vault_data, password, path."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unlock Vault")
        self.setMinimumSize(430, 300)

        self.vault_path = None
        self.vault_data = None
        self.vault_password = None
        self.vault_auth_method = "password"
        self._yubikey_worker = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Select vault file:"))

        self.select_btn = QPushButton("📂 Choose Vault File")
        self.select_btn.clicked.connect(self._choose_file)
        layout.addWidget(self.select_btn)

        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("Vault Password or Secondary Word")
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout.addWidget(self.pass_input)

        capability_label = QLabel("Optional capabilities for this session:")
        capability_label.setStyleSheet("color: #8fd; margin-top: 8px;")
        layout.addWidget(capability_label)

        self.allow_secret_viewing_checkbox = QCheckBox(
            "Allow viewing Swarm Keys and Vault details"
        )
        self.allow_secret_viewing_checkbox.setChecked(False)
        self.allow_secret_viewing_checkbox.setToolTip(
            "Off by default. When off, Phoenix hides and blocks secret-viewing actions."
        )
        layout.addWidget(self.allow_secret_viewing_checkbox)

        self.debug_output_checkbox = QCheckBox(
            "Enable Phoenix debug console output"
        )
        self.debug_output_checkbox.setChecked(False)
        self.debug_output_checkbox.setToolTip(
            "Off by default. Applies to the cockpit and session windows opened after sign-in."
        )
        layout.addWidget(self.debug_output_checkbox)

        self.close_on_minimize_or_sleep_checkbox = QCheckBox(
            "Close Phoenix on minimize or system sleep"
        )
        self.close_on_minimize_or_sleep_checkbox.setChecked(False)
        self.close_on_minimize_or_sleep_checkbox.setToolTip(
            "Off by default. When enabled, either event terminates Phoenix and all sessions."
        )
        layout.addWidget(self.close_on_minimize_or_sleep_checkbox)

        self.unlock_btn = QPushButton("🔓 Unlock Vault")
        self.unlock_btn.clicked.connect(self._unlock)
        self.unlock_btn.setDefault(True)
        layout.addWidget(self.unlock_btn)

        self.yubikey_btn = QPushButton("🔑 Unlock with YubiKey (Slot 2)")
        self.yubikey_btn.setToolTip(
            "Uses a preconfigured HMAC-SHA1 challenge-response slot. "
            "Phoenix never changes the YubiKey configuration."
        )
        self.yubikey_btn.clicked.connect(self._unlock_with_yubikey)
        layout.addWidget(self.yubikey_btn)

        self.yubikey_status = QLabel(
            "YubiKey mode expects HMAC-SHA1 slot 2 with touch required."
        )
        self.yubikey_status.setWordWrap(True)
        self.yubikey_status.setStyleSheet("color: #8fd; font-size: 11px;")
        layout.addWidget(self.yubikey_status)

        self.cancel_btn = QPushButton("❌ Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self.cancel_btn)

        self.unlock_btn.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

        self.selected_file_label = QLabel("                                                          ")
        self.selected_file_label.setWordWrap(True)
        self.selected_file_label.setStyleSheet("color: #aaa; font-size: 11px; font-style: italic; margin-left: 2px;")
        self.selected_file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.selected_file_label.setText(f"🔒 Selected:")
        layout.addWidget(self.selected_file_label)

    @property
    def allow_secret_viewing(self):
        return self.allow_secret_viewing_checkbox.isChecked()

    @property
    def debug_output(self):
        return self.debug_output_checkbox.isChecked()

    @property
    def close_on_minimize_or_sleep(self):
        return self.close_on_minimize_or_sleep_checkbox.isChecked()

    def showEvent(self, event):
        super().showEvent(event)

        # Ensure dialog is activated first
        self.activateWindow()
        self.raise_()

    def _choose_file(self):
        vault_dir = resolve_matrixswarm_base() / "vaults"
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Vault", str(vault_dir), "Vault Files (*.json)"
        )
        if not path:
            return

        self.selected_file_label.setText(f"🔒 Selected: {path}")
        self.vault_path = path

        # FORCE dialog to reclaim focus after modal QFileDialog
        self.activateWindow()
        self.raise_()

        # Now apply focus
        self.pass_input.setFocus(Qt.FocusReason.ActiveWindowFocusReason)


    def _unlock(self):
        if not self.vault_path:
            QMessageBox.warning(self, "Missing File", "Please select a vault.")
            return

        pw = self.pass_input.text().strip()
        if not pw:
            QMessageBox.warning(self, "Missing Password", "Enter vault password.")
            return

        self._attempt_unlock(pw)

    def _attempt_unlock(self, password, auth_method="password"):
        try:
            data = VaultService.load_vault(self.vault_path, password)
            if data is False:
                QMessageBox.warning(
                    self,
                    "Invalid Credential",
                    "The password or YubiKey credential did not unlock this vault.",
                )
                return
        except Exception:
            QMessageBox.critical(
                self,
                "Incorrect Credential",
                "The password or YubiKey credential is incorrect.",
            )

            if self.vault_path:
                self.pass_input.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
            else:
                self.select_btn.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
            return

        self.vault_password = password
        self.vault_data = data
        self.vault_auth_method = auth_method
        self.accept()

    def _unlock_with_yubikey(self):
        if not self.vault_path:
            QMessageBox.warning(self, "Missing File", "Please select a vault.")
            return

        secondary_word = self.pass_input.text().strip()
        if not secondary_word:
            QMessageBox.warning(
                self,
                "Missing Secondary Word",
                "Enter the YubiKey secondary word.",
            )
            return

        self._set_yubikey_busy(True, "Contacting YubiKey slot 2…")
        worker = YubiKeyCredentialWorker(secondary_word, self)
        self.pass_input.clear()
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
        self._attempt_unlock(password, auth_method="yubikey")

    def _on_yubikey_failed(self, message):
        self._set_yubikey_busy(False, "")
        self._yubikey_worker = None
        QMessageBox.warning(self, "YubiKey", message)

    def _set_yubikey_busy(self, busy, status):
        self.select_btn.setEnabled(not busy)
        self.unlock_btn.setEnabled(not busy)
        self.yubikey_btn.setEnabled(not busy)
        self.pass_input.setEnabled(not busy)
        self.allow_secret_viewing_checkbox.setEnabled(not busy)
        self.debug_output_checkbox.setEnabled(not busy)
        self.close_on_minimize_or_sleep_checkbox.setEnabled(not busy)
        self.yubikey_status.setText(status)

    def reject(self):
        if self._yubikey_worker and self._yubikey_worker.isRunning():
            self._yubikey_worker.cancel()
        super().reject()
