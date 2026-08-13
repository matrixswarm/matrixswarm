from matrix_gui.core.dispatcher import receiver
from matrix_gui.modules.net import packet_emitter, ws_client
from matrix_gui.modules.vault.crypto import cert_factory
from matrix_gui.modules.vault.services import vault_service_loader

modules = [
    receiver,
    packet_emitter,
    ws_client,
    vault_service_loader,
    cert_factory,
    #registry_loader
]

# initialize all modules
for module in modules:
    module.initialize()
    print("LOADING")

print("[BOOT] All core modules registered to EventBus.")
