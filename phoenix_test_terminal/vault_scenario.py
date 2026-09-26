"""Exercise production dialog signals and storage, using only synthetic credentials."""
from pathlib import Path
from unittest.mock import patch

PASSWORD = "PHOENIX-LAB-ONLY-not-a-real-credential-01"
ROTATED = "PHOENIX-LAB-ONLY-not-a-real-credential-02"
PROFILE = {"lab-only": {"label": "SYNTHETIC TEST PROFILE", "host": "server.example.invalid",
                        "port": 22, "username": "lab-user", "note": "Disposable offline fixture. Never use for a real server."}}


def run(stage, sandbox):
    from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
    from matrix_gui.modules.vault.vault_create_dialog import VaultCreateDialog
    from matrix_gui.modules.vault.vault_unlock_dialog import VaultUnlockDialog
    from matrix_gui.modules.vault.vault_change_password_dialog import VaultChangePasswordDialog
    from matrix_gui.modules.vault.vault_selector_dialog import VaultSelectorDialog
    from matrix_gui.modules.vault.vault_service import VaultService

    app = QApplication.instance() or QApplication([])
    vault = str(Path(sandbox) / "test-vault.json")
    checks = []

    def check(condition, label):
        if not condition:
            raise AssertionError(label)
        checks.append(label)

    # Real dialogs/signals/crypto; suppress native modal interaction only.
    with patch.object(QMessageBox, "warning"), patch.object(QMessageBox, "critical"), patch.object(QMessageBox, "information"), \
         patch.object(QFileDialog, "getSaveFileName", return_value=(vault, "")), \
         patch.object(QFileDialog, "getOpenFileName", return_value=(vault, "")):
        if stage == "create":
            check(not Path(vault).exists(), "No pre-existing vault")
            for choice in ("create", "unlock", "change"):
                selector = VaultSelectorDialog()
                getattr(selector, f"{choice}_btn").click()
                check(selector.selection == choice and selector.result() == QDialog.DialogCode.Accepted, f"Selector routes {choice}")
            selector = VaultSelectorDialog()
            selector.cancel_btn.click()
            check(selector.result() == QDialog.DialogCode.Rejected and selector.selection is None, "Selector cancellation")
            create = VaultCreateDialog()
            create.create_btn.click()
            check(not Path(vault).exists(), "Empty password creates no vault")
            create.password_input.setText(PASSWORD)
            with patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
                create.create_btn.click()
            check(not Path(vault).exists() and create.result() != QDialog.DialogCode.Accepted, "File selection cancellation creates no vault")
            create.create_btn.click()
            check(create.result() == QDialog.DialogCode.Accepted and Path(vault).is_file(), "Create signal writes encrypted vault")
            data = VaultService.load_vault(vault, PASSWORD)
            check(isinstance(data, dict) and all(name in data for name in ("registry", "deployments", "workspaces")), "New vault has required initial sections")
            check(PASSWORD not in Path(vault).read_text(), "Password not written as plaintext")
        else:
            unlock = VaultUnlockDialog()
            check(not unlock.allow_secret_viewing and not unlock.debug_output, "Safe unlock defaults")
            unlock.select_btn.click()
            unlock.pass_input.setText("deliberately-wrong-test-credential")
            unlock.unlock_btn.click()
            check(unlock.result() != QDialog.DialogCode.Accepted and unlock.vault_data is None, "Wrong password rejected")
            unlock.pass_input.setText(ROTATED if stage == "verify-rotation" else PASSWORD)
            unlock.unlock_btn.click()
            check(unlock.result() == QDialog.DialogCode.Accepted and isinstance(unlock.vault_data, dict), "Fresh interpreter unlocks persisted vault")
            if stage == "persist":
                from matrix_gui.core.event_bus import EventBus
                from matrix_gui.modules.vault.services import vault_service_loader
                from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton

                # Use production event registration: do not replace EventBus with a fake.
                EventBus.clear()
                vault_service_loader.initialize()
                VaultService.initialize_runtime(unlock.vault_data, PASSWORD, vault)
                core = VaultCoreSingleton.get()
                for name in ("registry", "deployments", "workspaces", "directives", "connection_manager"):
                    check(core.get_store(name) is not None, f"Runtime store available: {name}")
                check(core.get_store("registry").set_namespace("ssh", PROFILE), "Registry commit accepted")
                check(VaultService.load_vault(vault, PASSWORD)["registry"]["ssh"] == PROFILE, "Save event persisted registry to encrypted disk")
            elif stage == "reopen":
                check(unlock.vault_data["registry"]["ssh"] == PROFILE, "Registry survives process restart")
            elif stage == "rotate":
                change = VaultChangePasswordDialog()
                change.select_btn.click()
                change.old_pw.setText(PASSWORD)
                change.new_pw.setText(ROTATED)
                change.change_btn.click()
                check(change.result() == QDialog.DialogCode.Accepted, "Password rotation signal accepted")
            elif stage == "verify-rotation":
                check(unlock.vault_data["registry"]["ssh"] == PROFILE, "Rotation preserves data across process restart")
                check(VaultService.load_vault(vault, PASSWORD) is False, "Old password rejected after rotation")
            else:
                raise ValueError("Unknown vault stage")
    app.processEvents()
    return checks
