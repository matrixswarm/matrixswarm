from matrix_gui.core.event_bus import EventBus
from pathlib import Path
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.modules.vault.crypto.vault_handler import (
    load_vault_singlefile,
    save_vault_singlefile,
)


class VaultBusyError(RuntimeError):
    """Rotation requires a closed vault with all accepted writes completed."""

class VaultUnlockError(ValueError):
    """Decryption did not produce vault data."""


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
    def initialize_runtime(
        vault_data: dict,
        password: str,
        path: str,
        auth_method: str = "password",
    ):
        """Initialize the cockpit vault and publish session authentication metadata."""
        auth_method = (
            "yubikey"
            if str(auth_method).strip().casefold() == "yubikey"
            else "password"
        )
        VaultCoreSingleton.initialize(
            vault_data=vault_data,
            password=password,
            vault_path=path
        )

        EventBus.emit(
            "vault.unlocked",
            vault_path=path,
            password=password,
            vault_data=vault_data,
            auth_method=auth_method,
        )

    @staticmethod
    def change_password(path: str, old_pw: str, new_pw: str):
        """Load vault with old password, re-save with new password."""
        core = VaultCoreSingleton._instance
        if core is not None and Path(path).resolve() == core.vault_path.resolve():
            if not core._closed or core._workspace_active is not None or core._workspace_queue:
                raise VaultBusyError("Close this vault and wait for pending saves before changing its password.")
        data = load_vault_singlefile(old_pw, path)
        if not isinstance(data, dict):
            raise VaultUnlockError("Vault could not be unlocked; password was not changed")
        save_vault_singlefile(data, new_pw, path)
        return data
