from matrix_gui.core.event_bus import EventBus

# Stores vault metadata globally if needed by cockpit/UI
_vault_data = None


def on_vault_unlocked(**kwargs):
    """
    Global hook for vault unlock.
    Stores vault metadata for cockpit/UI modules.
    Session dispatchers are no longer armed here – they are armed
    per-session against their SessionBus inside the subprocess.
    """
    global _vault_data
    _vault_data = kwargs.get("vault_data")
    vault_path = kwargs.get("vault_path")
    password = kwargs.get("password")

    print("[SWARM] Vault unlocked → metadata stored")
    print(f"        Vault: {vault_path}")
    print(f"        Password length: {len(password) if password else 'N/A'}")


def initialize():
    """
    Module entrypoint: register vault unlock hook.
    Only global vault lifecycle events are handled here.
    """
    EventBus.on("vault.unlocked", on_vault_unlocked)
    print("[DISPATCHERS] Online (global). Listening for vault.unlocked...")

