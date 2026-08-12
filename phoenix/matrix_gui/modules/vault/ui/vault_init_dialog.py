from PyQt6.QtWidgets import QVBoxLayout, QLabel, QPushButton, QLineEdit, QMessageBox, QDialog
from matrix_gui.modules.vault.crypto.vault_handler import save_vault_singlefile
from matrix_gui.util.resolve_matrixswarm_base import resolve_matrixswarm_base
from matrix_gui.modules.vault.ui.vault_popup import VaultPasswordDialog

class VaultInitDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Vault")
        self.setFixedSize(360, 180)

        self.vault_path = None
        self.vault_key_path = None
        self.vault_password = None

        self.label = QLabel("Enter a password to create your new vault.")

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Vault Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.create_button = QPushButton("🛠 Create Vault")
        self.create_button.clicked.connect(self.create_vault)

        self.cancel_button = QPushButton("❌ Cancel")
        self.cancel_button.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.password_input)
        layout.addWidget(self.create_button)
        layout.addWidget(self.cancel_button)

    def create_vault(self):
        password = self.password_input.text().strip()
        if not password:
            QMessageBox.warning(self, "Invalid Password", "Password cannot be empty.")
            return

        base_path = resolve_matrixswarm_base()
        vault_dir = base_path / "matrix_gui" / "vaults"
        vault_dir.mkdir(parents=True, exist_ok=True)

        # ⬇ Replace hardcoded name with interactive save dialog
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Save New Vault As", str(vault_dir), "Vault Files (*.json)")
        if not path:
            return  # cancelled
        if not path.endswith(".json"):
            path += ".json"
        data_path = path

        vault_data = {
            "last_known_host": "",
            "authorized_keys": {}, #ssh
            "known_hosts": {}, #ssh
            "connection_manager": {},
            "deployments": {},
            "directives": {}
        }

        try:
            save_vault_singlefile(vault_data, password, data_path)
        except Exception as e:
            QMessageBox.critical(self, "Vault Error", f"Failed to save vault:\n{str(e)}")
            return

        self.vault_path = data_path
        self.vault_password = password
        self.accept()

    def unlock_vault_flow(self):
        dialog = VaultPasswordDialog(self)
        result = dialog.exec()

        # User canceled or dialog closed unexpectedly
        if result != QDialog.DialogCode.Accepted:
            return None, None, None

        # Defensive getters to avoid missing attributes
        vault_file = getattr(dialog, "vault_file_path", None)
        vault_key = getattr(dialog, "vault_key_path", None)
        vault_pass = getattr(dialog, "vault_password", None)

        # Validation guard
        if not vault_file:
            QMessageBox.warning(
                self,
                "No Vault Selected",
                "Please select a vault file before entering a password."
            )
            return None, None, None

        return vault_file, vault_key, vault_pass

