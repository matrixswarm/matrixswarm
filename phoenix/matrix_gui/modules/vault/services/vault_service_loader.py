from matrix_gui.core.event_bus import EventBus
from matrix_gui.modules.vault.crypto.vault_handler import save_vault_singlefile
from PyQt6.QtWidgets import QMessageBox
import threading

def run_with_timeout(func, timeout, *args, **kwargs):
    """
    Run a function with a timeout.
    Returns (result, error). If timeout occurs, error is TimeoutError.
    """
    result = {"value": None, "error": None}

    def target():
        try:
            result["value"] = func(*args, **kwargs)
        except Exception as e:
            result["error"] = e

    t = threading.Thread(target=target)
    t.start()
    t.join(timeout)

    if t.is_alive():
        return None, TimeoutError("Vault save timed out")
    if result["error"]:
        return None, result["error"]
    return result["value"], None


class VaultEncryptionService:
    service_id = "EncryptionService"

    def __init__(self, vault_data, password):
        self.vault_data = vault_data
        self.password = password

    def encrypt(self, data):
        return f"[ENTOMBED] {data}"


def register_encryption_service(**kwargs):
    service = VaultEncryptionService(kwargs["vault_data"], kwargs["password"])
    print("[SERVICE] EncryptionService registered from vault")
    return service


def provide_encryption_service(**kwargs):
    return EventBus._encryption_service if hasattr(EventBus, "_encryption_service") else None

def handle_vault_update(event_data):
    try:
        vault_path = event_data.get("vault_path")
        password = event_data.get("password")
        data = event_data.get("data")

        if not vault_path:
            print("[VAULT ERROR] vault_path is missing or None in vault.update event.")
            return

        save_vault_singlefile(data, password, vault_path)
        print(f"[VAULT] Updated and saved to {vault_path}")
    except Exception as e:
        print(f"[VAULT ERROR] Failed to save vault: {e}")

def _on_vault_update(**kw):
    try:
        path = kw.get("vault_path")
        password = kw.get("password")
        data = kw.get("data")

        if not (path and isinstance(data, dict)):
            print("[VAULT][ERROR] bad args to vault.update:", {"path": path, "data?": isinstance(data, dict)})
            EventBus.emit("vault.save_error", error="bad args")
            return

        print(f"[VAULT] 💾 Attempting vault save → {path}")

        # ---- TIMEOUT CALL HERE ----
        _, error = run_with_timeout(
            save_vault_singlefile,
            timeout=5,
            data=data,
            password=password,
            data_path=path
        )

        if error:
            print(f"[VAULT][ERROR] SAVE TIMEOUT: {error}")

            try:
                QMessageBox.critical(
                    None,
                    "Vault Save Failed",
                    f"The vault could not be saved due to timeout.\n\n"
                    f"Path:\n{path}\n\n"
                    f"Your previous vault backup is still safe."
                )
            except Exception as popup_err:
                print(f"[VAULT][WARN] Could not show popup: {popup_err}")

            EventBus.emit("vault.save_error", error=str(error))
            return

        print(f"[VAULT] saved → {path}")
        EventBus.emit("vault.saved", vault_path=path)

    except Exception as e:
        print("[VAULT][ERROR] save failed:", e)
        EventBus.emit("vault.save_error", error=str(e))

def initialize():
    EventBus.on("vault.unlocked", lambda **kwargs: setattr(EventBus, "_encryption_service", VaultEncryptionService(kwargs["vault_data"], kwargs["password"])))
    EventBus.on("service.request.encryption", provide_encryption_service)
    EventBus.on("vault.update", _on_vault_update)
    print("[VAULT] Service loader initialized.")
