import importlib
import traceback

class PacketDeliveryFactoryMixin:
    def __init__(self):
        self._last_delivery_agent = None

    def get_delivery_agent(self, path: str, new=True):
        """
        Loads a delivery agent from a dotted path like: 'file.json_file'
        Falls back to agent/error/delivery_agent_not_found.py
        """
        try:
            full_path = f"core.class_lib.packet_delivery.delivery_agent.{path}.delivery_agent"
            mod = importlib.import_module(full_path)
            agent = mod.DeliveryAgent()
            if new:
                return agent
            else:
                self._last_delivery_agent = agent
                return self._last_delivery_agent
        except Exception as e:
            print(f"[DELIVERY][ERROR] Could not import delivery agent '{path}': {e}")
            traceback.print_exc()
            try:
                from core.class_lib.packet_delivery.delivery_agent.error.delivery_agent_not_found import DeliveryAgent as Fallback
                return Fallback(reason=f"Delivery agent '{path}' not found.")
            except Exception as fallback_err:
                print(f"[DELIVERY][FAILSAFE] Failed to load fallback delivery agent: {fallback_err}")
                return None
