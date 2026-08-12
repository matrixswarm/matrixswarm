from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt, QTimer
from .vault_service import VaultService
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

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Select vault file:"))

        self.select_btn = QPushButton("📂 Choose Vault File")
        self.select_btn.clicked.connect(self._choose_file)
        layout.addWidget(self.select_btn)

        self.pass_input = QLineEdit()
        self.pass_input.setPlaceholderText("Vault Password")
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout.addWidget(self.pass_input)

        self.unlock_btn = QPushButton("🔓 Unlock Vault")
        self.unlock_btn.clicked.connect(self._unlock)
        self.unlock_btn.setDefault(True)
        layout.addWidget(self.unlock_btn)

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

        try:
            data = VaultService.load_vault(self.vault_path, pw)
            if data==False:
                QMessageBox.warning(self, "Invalid Password", "Enter vault password.")
                return
        except Exception:
            QMessageBox.critical(self, "Incorrect Password", "Password is incorrect.")

            # Reset focus depending on state
            if self.vault_path:
                self.pass_input.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
            else:
                self.select_btn.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
            return

        self.vault_password = pw
        self.vault_data = data
        self.accept()
