import time
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QFileDialog
)
from matrix_gui.util.resolve_matrixswarm_base import resolve_matrixswarm_base
from .vault_service import VaultService

class VaultCreateDialog(QDialog):
    """Creates a new vault and returns {vault_path, password}."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Vault")
        self.setFixedSize(360, 180)

        self.vault_path = None
        self.vault_password = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Enter a password for your new vault:"))

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Vault Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.password_input)

        self.create_btn = QPushButton("🛠 Create Vault")
        self.cancel_btn = QPushButton("❌ Cancel")

        self.create_btn.clicked.connect(self._create)
        self.cancel_btn.clicked.connect(self.reject)

        layout.addWidget(self.create_btn)
        layout.addWidget(self.cancel_btn)

    def _create(self):
        pw = self.password_input.text().strip()
        if not pw:
            QMessageBox.warning(self, "Invalid Password", "Password cannot be empty.")
            return

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
            VaultService.save_vault(path, initial_data, pw)
        except Exception as e:
            QMessageBox.critical(self, "Vault Error", f"Failed to create vault:\n{e}")
            return

        self.vault_path = path
        self.vault_password = pw
        self.accept()
