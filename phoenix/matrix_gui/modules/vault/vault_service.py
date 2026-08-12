from matrix_gui.core.event_bus import EventBus
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.modules.vault.crypto.vault_handler import (
    load_vault_singlefile,
    save_vault_singlefile,
)


class VaultService:
    """Backend for all vault operations (load, save, change-password, init)."""

    @staticmethod
    def load_vault(path: str, password: str):
        """Return dict or raise Exception."""
        return load_vault_singlefile(password, path)

    @staticmethod
    def save_vault(path: str, data: dict, password: str):
        save_vault_singlefile(data, password, path)

    @staticmethod
    def initialize_runtime(vault_data: dict, password: str, path: str):
        """Initialize the running Phoenix cockpit vault + emit event."""
        VaultCoreSingleton.initialize(
            vault_data=vault_data,
            password=password,
            vault_path=path
        )

        EventBus.emit(
            "vault.unlocked",
            vault_path=path,
            password=password,
            vault_data=vault_data
        )

    @staticmethod
    def change_password(path: str, old_pw: str, new_pw: str):
        """Load vault with old password, re-save with new password."""
        data = load_vault_singlefile(old_pw, path)
        save_vault_singlefile(data, new_pw, path)
        return data
