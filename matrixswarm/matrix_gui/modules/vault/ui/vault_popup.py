from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QLineEdit, QMessageBox, QFileDialog
import os
from matrix_gui.util.resolve_matrixswarm_base import resolve_matrixswarm_base
from matrix_gui.core.event_bus import EventBus
from matrix_gui.modules.vault.crypto.vault_handler import load_vault_singlefile
from matrix_gui.modules.vault.services.vault_singleton import VaultSingleton
from matrix_gui.modules.vault.services.vault_obj import VaultObj
from matrix_gui.modules.vault.ui.vault_init_dialog import VaultInitDialog

class VaultPasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unlock Vault")
        self.setFixedSize(360, 220)

        self.vault_file_path = None
        self.vault_key_path = None
        self.vault_password = None
        self.vault_created = False

        self.label = QLabel("Select a vault file and enter the password.")

        self.select_button = QPushButton("📂 Select Vault")
        self.select_button.clicked.connect(self.select_vault_file)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Vault Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.returnPressed.connect(self.auto_trigger_unlock)

        self.unlock_button = QPushButton("🔓 Unlock Vault")
        self.unlock_button.clicked.connect(self.unlock_vault)

        self.create_button = QPushButton("🆕 Create New Vault")
        self.create_button.clicked.connect(self.create_vault)

        self.cancel_button = QPushButton("❌ Cancel")
        self.cancel_button.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.select_button)
        layout.addWidget(self.password_input)
        layout.addWidget(self.unlock_button)
        layout.addWidget(self.create_button)
        layout.addWidget(self.cancel_button)

        self._unlock_fired = False

    def select_vault_file(self):
        vault_dir = resolve_matrixswarm_base() / "matrix_gui" / "vaults"
        vault_dir.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(self, "Select Vault File", str(vault_dir), "Vault Files (*.json)")
        if not path:
            return

        self.vault_file_path = path
        self.label.setText(f"Selected Vault: {os.path.basename(path)}")
        if not self.password_input.text().strip():
            self.password_input.setFocus()  # 🛡️ Send cursor to password input
        else:
            self.unlock_button.setFocus()  # 🟢 Ready for Enter key launch

    def unlock_vault(self):


        if self._unlock_fired:
            print("[VAULT/UI] duplicate unlock ignored")
            self._unlock_fired = True
            return

        password = self.password_input.text().strip()
        if not password:
            QMessageBox.warning(self, "Missing Password", "Please enter the vault password.")
            return

        if not os.path.exists(self.vault_file_path):
            QMessageBox.critical(self, "Vault Error", "Vault file does not exist.")
            return


        try:
            vault_data = load_vault_singlefile (password, self.vault_file_path)
            self.vault_password = password

            vault_obj = VaultObj(
                path=self.vault_file_path,
                vault=vault_data,
                password=password
            )
            VaultSingleton.set(vault_obj)


        except Exception as e:
            QMessageBox.critical(self, "Vault Load Failed", f"Vault could not be decrypted:\n{e}")
            return

        EventBus.emit("vault.unlocked",
                      vault_path=self.vault_file_path,
                      password=self.vault_password,
                      vault_data=vault_data)

        self.accept()
        self._unlock_fired = True

    def auto_trigger_unlock(self):
        if not self.vault_file_path:
            QMessageBox.warning(self, "No Vault Selected", "Please select a vault file before unlocking.")
            return

        if not self.password_input.text().strip():
            QMessageBox.warning(self, "Missing Password", "Please enter a vault password.")
            return

        self.unlock_vault()

    def create_vault(self):

        dlg = VaultInitDialog(self)
        if dlg.exec_() == dlg.Accepted:
            self.vault_file_path = dlg.vault_path
            self.vault_password = dlg.vault_password
            # If you want: automatically unlock the new vault after creation
            try:
                from matrix_gui.modules.vault.crypto.vault_handler import load_vault_singlefile
                vault_data = load_vault_singlefile(self.vault_password, self.vault_file_path)

                from matrix_gui.modules.vault.services.vault_obj import VaultObj
                vault_obj = VaultObj(
                    path=self.vault_file_path,
                    vault=vault_data,
                    password=self.vault_password
                )
                from matrix_gui.modules.vault.services.vault_singleton import VaultSingleton
                VaultSingleton.set(vault_obj)
                from matrix_gui.core.event_bus import EventBus
                EventBus.emit("vault.unlocked",
                              vault_path=self.vault_file_path,
                              password=self.vault_password,
                              vault_data=vault_data)
                self.accept()
            except Exception as e:
                QMessageBox.critical(self, "Vault Creation Failed", f"Failed to create and unlock new vault:\n{e}")
                return
        # else: user cancelled, do nothing
