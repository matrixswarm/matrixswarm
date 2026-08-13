from matrix_gui.core.event_bus import EventBus
#from matrix_gui.modules.net.channel_state import ChannelState
from matrix_gui.core.class_lib.packet_delivery.mixin.packet_factory_mixin import PacketFactoryMixin
import requests

class PacketEmitter(PacketFactoryMixin):
    def __init__(self):
        print("[EMITTER] Ready to transmit.")

    def inject_agent(self, agent_id, payload):


        state = ChannelState.dump()
        if not state["host"] or not state["cert"] or not state["key"]:
            print("[EMITTER] Incomplete channel config. Aborting.")
            return

        print(f"[EMITTER] Dispatching to {agent_id}@{state['host']} ({state['protocol']})")

        pk1 = self.get_delivery_packet("standard.command.packet")
        pk1.set_data({"handler": "cmd_forward_command"})

        pk2 = self.get_delivery_packet("standard.general.json.packet")
        pk2.set_data({"target_universal_id": agent_id, "folder": "incoming"})

        pk3 = self.get_delivery_packet("standard.general.json.packet")
        if "session_id" not in payload:
            payload["session_id"] = state.get("session_id")
        pk3.set_data(payload)

        pk2.set_packet(pk3, "command")
        pk1.set_packet(pk2, "content")

        try:
            url = f"{state['protocol']}://{state['host']}:{state['port']}"
            response = requests.post(
                url=url,
                json=pk1.get_packet(),
                cert=(state["cert"], state["key"]),
                verify=False,
                timeout=5
            )
            print(f"[EMITTER] HTTP {response.status_code}: {response.text[:64]}...")
        except Exception as e:
            print(f"[EMITTER][ERROR] {e}")

emitter = PacketEmitter()

def initialize():
    EventBus.on("agent.injected", emitter.inject_agent)
    print("[EMITTER] Initialized.")