import os
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QLineEdit, QMessageBox, QFileDialog
from matrix_gui.util.resolve_matrixswarm_base import resolve_matrixswarm_base
from matrix_gui.core.event_bus import EventBus
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.modules.vault.ui.vault_password_change_dialog import VaultPasswordChangeDialog
from matrix_gui.modules.vault.crypto.vault_handler import load_vault_singlefile


class VaultPasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unlock Vault")

        self.setMinimumWidth(280)

        self.setMinimumHeight(300)  # give it a good default size

        self.vault_file_path = None
        self.vault_key_path = None
        self.vault_password = None
        self.vault_created = False

        self.label = QLabel("Select a vault file and enter the password.")

        self.select_button = QPushButton("📂 Select Vault")
        self.select_button.clicked.connect(self.select_vault_file)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Vault Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.returnPressed.connect(self.auto_trigger_unlock)

        self.unlock_button = QPushButton("🔓 Unlock Vault")
        self.unlock_button.clicked.connect(self.unlock_vault)

        self.create_button = QPushButton("🆕 Create New Vault")
        self.create_button.clicked.connect(self.create_vault)

        self.cancel_button = QPushButton("❌ Cancel")
        self.cancel_button.clicked.connect(self.reject)

        self.change_pw_btn = QPushButton("🔑 Change Password")
        self.change_pw_btn.clicked.connect(self.change_password)

        self.unlock_button.setObjectName("primary")
        self.cancel_button.setObjectName("danger")
        self.change_pw_btn.setObjectName("key")

        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.select_button)
        layout.addWidget(self.password_input)
        layout.addWidget(self.unlock_button)
        layout.addWidget(self.create_button)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.change_pw_btn)
        layout.setSpacing(7)  # space between rows
        layout.setContentsMargins(10, 8, 10, 8)
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
            self.password_input.setFocus()
        else:
            self.unlock_button.setFocus()

    def unlock_vault(self):
        # Guard against double trigger
        if self._unlock_fired:
            print("[VAULT/UI] duplicate unlock ignored")
            return

        password = self.password_input.text().strip()
        if not password:
            QMessageBox.warning(self, "Missing Password", "Please enter the vault password.")
            return

        if not self.vault_file_path:
            QMessageBox.warning(self, "No Vault Selected", "Please select a vault file first.")
            return

        if not os.path.exists(self.vault_file_path):
            QMessageBox.critical(self, "Vault Error", "Vault file does not exist.")
            return


        try:

            try:
                vault_data = load_vault_singlefile(password, self.vault_file_path)
            except Exception as e:
                QMessageBox.critical(self, "Incorrect Password","The password you entered is not correct.\nPlease try again.")
                self.password_input.clear()
                self.password_input.setFocus()
                return

            if vault_data is None:
                QMessageBox.critical(
                    self,
                    "Incorrect Password",
                    "The password you entered is not correct.\nPlease try again."
                )
                self.password_input.clear()
                self.password_input.setFocus()
                self._unlock_fired = False  # ensure unlock flow stays open
                return

            self.vault_password = password

            if not vault_data or not vault_data.get("deployments"):
                from matrix_gui.modules.vault.ui.vault_init_dialog import VaultInitDialog
                dlg = VaultInitDialog(self)
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    return  # user cancelled → stay locked
                # user created/selects vault → overwrite vault_data
                vault_data = dlg.vault_data

            try:
                VaultCoreSingleton.initialize(
                    vault_data=vault_data,
                    password=self.vault_password,
                    vault_path=self.vault_file_path
                )
            except Exception as e:
                print(str(e))


        except Exception as e:
            QMessageBox.critical(self, "Vault Load Failed", f"Vault could not be decrypted:\n{e}")
            return

        EventBus.emit(
            "vault.unlocked",
            vault_path=self.vault_file_path,
            password=self.vault_password,
            vault_data=vault_data
        )

        self._unlock_fired = True
        self.accept()

    def auto_trigger_unlock(self):
        if not self.vault_file_path:
            QMessageBox.warning(self, "No Vault Selected", "Please select a vault file before unlocking.")
            return

        if not self.password_input.text().strip():
            QMessageBox.warning(self, "Missing Password", "Please enter a vault password.")
            return

        self.unlock_vault()

    def create_vault(self):
        from matrix_gui.modules.vault.ui.vault_init_dialog import VaultInitDialog
        dlg = VaultInitDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.vault_file_path = dlg.vault_path
            self.vault_password = dlg.vault_password
            # If you want: automatically unlock the new vault after creation
            try:

                vault_data = load_vault_singlefile(self.vault_password, self.vault_file_path)

                VaultCoreSingleton.initialize(
                    vault_data=vault_data,
                    password=self.vault_password,
                    vault_path=self.vault_file_path
                )

                EventBus.emit("vault.unlocked",
                              vault_path=self.vault_file_path,
                              password=self.vault_password,
                              vault_data=vault_data)

                self.accept()
            except Exception as e:
                QMessageBox.critical(self, "Vault Creation Failed", f"Failed to create and unlock new vault:\n{e}")
                return
        # else: user cancelled, do nothing

    def change_password(self):
        if not self.vault_file_path:
            QMessageBox.warning(self, "No Vault", "Please select a vault first.")
            return
        dlg = VaultPasswordChangeDialog(self.vault_file_path, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # After success, set new password for next unlock
            self.vault_password = dlg.new_password
            QMessageBox.information(self, "Next Step", "Vault password has been updated. Please unlock with the new password.")