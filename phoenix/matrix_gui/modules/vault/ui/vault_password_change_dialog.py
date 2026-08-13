import os
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
from matrix_gui.modules.vault.crypto.vault_handler import load_vault_singlefile, save_vault_singlefile

class VaultPasswordChangeDialog(QDialog):
    def __init__(self, vault_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change Vault Password")
        self.setFixedSize(400, 260)

        self.vault_path = vault_path
        self.new_password = None

        layout = QVBoxLayout(self)

        self.info = QLabel("Enter your current vault password and a new one.")
        layout.addWidget(self.info)

        self.old_pw = QLineEdit()
        self.old_pw.setPlaceholderText("Current Password")
        self.old_pw.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.old_pw)

        self.new_pw = QLineEdit()
        self.new_pw.setPlaceholderText("New Password")
        self.new_pw.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.new_pw)

        self.confirm_pw = QLineEdit()
        self.confirm_pw.setPlaceholderText("Confirm New Password")
        self.confirm_pw.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.confirm_pw)

        self.change_btn = QPushButton("🔑 Change Password")
        self.change_btn.clicked.connect(self.change_password)
        layout.addWidget(self.change_btn)

        self.cancel_btn = QPushButton("❌ Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self.cancel_btn)


    def change_password(self):
        old_pw = self.old_pw.text().strip()
        new_pw = self.new_pw.text().strip()
        confirm_pw = self.confirm_pw.text().strip()

        if not old_pw or not new_pw:
            QMessageBox.warning(self, "Missing Fields", "All fields are required.")
            return
        if new_pw != confirm_pw:
            QMessageBox.warning(self, "Mismatch", "New password and confirmation do not match.")
            return
        if not os.path.exists(self.vault_path):
            QMessageBox.critical(self, "Vault Error", "Vault file does not exist.")
            return

        try:
            # 1. Decrypt with old password
            vault_data = load_vault_singlefile(old_pw, self.vault_path)

            # 2. Re-encrypt with new password (atomic save)
            save_vault_singlefile(vault_data, new_pw, self.vault_path)

            self.new_password = new_pw
            QMessageBox.information(self, "Success", "Vault password changed successfully.")
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to change password:\n{e}")
            return
