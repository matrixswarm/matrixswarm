import base64
from core.class_lib.packet_delivery.utility.encryption.config import ENCRYPTION_CONFIG
from core.class_lib.packet_delivery.utility.crypto_processors.packet_encryption_factory import packet_encryption_factory
import importlib
import traceback

class PacketDeliveryFactoryMixin:
    def _ensure_crypto_setup(self):
        if not hasattr(self, '_decoded_swarm_key'):
            swarm_key = ENCRYPTION_CONFIG.get_swarm_key()
            self._decoded_swarm_key = base64.b64decode(swarm_key) if swarm_key else b''

    def get_delivery_agent(self, path: str, new=True, **kwargs):

        try:
            self._ensure_crypto_setup()
            full_path = f"core.class_lib.packet_delivery.delivery_agent.{path}.delivery_agent"
            mod = importlib.import_module(full_path)
            agent = mod.DeliveryAgent()
            if new:
                mode = "encrypt" if ENCRYPTION_CONFIG.is_enabled() else "plaintext_encrypt"
                agent.set_crypto_handler(packet_encryption_factory(mode, self._decoded_swarm_key, priv_key=kwargs.get("priv_key")))
            return agent
        except Exception as e:
            print(f"[DELIVERY][ERROR] Could not import delivery agent '{path}': {e}")
            traceback.print_exc()
            try:
                from core.class_lib.packet_delivery.delivery_agent.error.delivery_agent_not_found import DeliveryAgent as Fallback
                return Fallback(reason=f"Delivery agent '{path}' not found.")
            except Exception as fallback_err:
                print(f"[DELIVERY][FAILSAFE] Failed to load fallback delivery agent: {fallback_err}")
                return None