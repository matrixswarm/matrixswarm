import base64
import importlib
import traceback
from core.class_lib.packet_delivery.utility.encryption.config import ENCRYPTION_CONFIG
from core.class_lib.packet_delivery.utility.crypto_processors.packet_encryption_factory import packet_encryption_factory

class PacketReceptionFactoryMixin:
    def _ensure_crypto_setup(self):
        if not hasattr(self, '_decoded_swarm_key'):
            swarm_key = ENCRYPTION_CONFIG.get_swarm_key()
            self._decoded_swarm_key = base64.b64decode(swarm_key) if swarm_key else b''

    def get_reception_agent(self, path: str, new=True, **kwargs):

        try:
            self._ensure_crypto_setup()
            full_path = f"core.class_lib.packet_delivery.reception_agent.{path}.reception_agent"
            mod = importlib.import_module(full_path)
            agent = mod.ReceptionAgent()
            if new:
                mode = "decrypt" if ENCRYPTION_CONFIG.is_enabled() else "plaintext"
                agent.set_crypto_handler(packet_encryption_factory(mode, self._decoded_swarm_key, pub_key=kwargs.get("pub_key")))


            return agent
        except Exception as e:
            print(f"[RECEPTION][ERROR] Could not import reception agent '{path}': {e}")
            traceback.print_exc()
            try:
                from core.class_lib.packet_delivery.reception_agent.error.reception_agent_not_found import ReceptionAgent as Fallback
                return Fallback(reason=f"Reception agent '{path}' not found.")
            except Exception as fallback_err:
                print(f"[RECEPTION][FAILSAFE] Failed to load fallback reception agent: {fallback_err}")
                return None