from matrix_gui.core.event_bus import EventBus


def on_vault_unlocked(**kwargs):
    vault_path = kwargs.get("vault_path")
    key_path = kwargs.get("key_path")
    password = kwargs.get("password")

    print("[SWARM] Vault unlocked!")
    print(f"        Vault: {vault_path}")
    print(f"        Key:   {key_path}")
    print(f"        Password (masked): {'*' * len(password) if password else 'N/A'}")
    # TODO: load keys, bootstrap swarm, etc.

def initialize():
    # Register listener at import time
    EventBus.on("vault.unlocked", on_vault_unlocked)
    print("[SWARM] Receiver online. Listening for vault.unlocked...")