from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QLineEdit,
    QMessageBox, QFileDialog
)
from .vault_service import VaultService
from matrix_gui.util.resolve_matrixswarm_base import resolve_matrixswarm_base

class VaultChangePasswordDialog(QDialog):
    """Allows user to change password of an existing vault."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change Vault Password")
        self.setFixedSize(360, 220)

        self.vault_path = None

        layout = QVBoxLayout(self)

        self.select_btn = QPushButton("📂 Select Vault")
        self.select_btn.clicked.connect(self._choose_file)
        layout.addWidget(self.select_btn)

        self.old_pw = QLineEdit()
        self.old_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.old_pw.setPlaceholderText("Old Password")
        layout.addWidget(self.old_pw)

        self.new_pw = QLineEdit()
        self.new_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pw.setPlaceholderText("New Password")
        layout.addWidget(self.new_pw)

        self.change_btn = QPushButton("🔑 Change Password")
        self.change_btn.clicked.connect(self._change)
        self.change_btn.setDefault(True)
        layout.addWidget(self.change_btn)

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

        try:
            data = VaultService.change_password(self.vault_path, old_pw, new_pw)
        except Exception:
            QMessageBox.critical(self, "Error", "Old password is incorrect.")
            return

        self.result_data = data
        self.result_password = new_pw
        QMessageBox.information(self, "Success", "Password updated.")
        self.accept()
