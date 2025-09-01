from .inbound_dispatcher import InboundDispatcher
from .outbound_dispatcher import OutboundDispatcher
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.event_bus import EventBus

_dispatchers = None

def on_vault_unlocked(**kwargs):
    """
    Called when the vault is unlocked.
    Arms Inbound and Outbound dispatchers once per process.
    """
    vault_data = kwargs.get("vault_data")
    password = kwargs.get("password")
    vault_path = kwargs.get("vault_path")

    # 🔎 Vault info print
    print("[SWARM] Vault unlocked!")
    print(f"        Vault: {vault_path}")
    print(f"        Password (masked): {'*' * len(password) if password else 'N/A'}")

    global _dispatchers
    if _dispatchers:
        return  # already armed

    try:
        inbound = InboundDispatcher(EventBus)
        outbound = OutboundDispatcher(EventBus, get_sessions(), vault_data)
        _dispatchers = (inbound, outbound)
        print("[DISPATCHERS] ✅ Inbound/Outbound dispatchers armed")
    except Exception as e:
        print(f"[DISPATCHERS] ❌ Failed to initialize dispatchers: {e}")

def initialize():
    """
    Module entrypoint: register vault unlock hook.
    """
    EventBus.on("vault.unlocked", on_vault_unlocked)
    print("[DISPATCHERS] Online. Listening for vault.unlocked...")
