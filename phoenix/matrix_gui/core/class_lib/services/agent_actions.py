"""Shared Phoenix operations used by GUI and terminal session adapters."""
import time
import uuid

from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet


def restart_agent(bus, session_id, agent_id, full_subtree=False, token=None):
    """Submit through Phoenix's existing signed/encrypted outgoing pipeline."""
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValueError("Agent identity is required.")
    packet = Packet()
    packet.set_data({
        "handler": "cmd_restart_subtree",
        "content": {
            "target_universal_id": agent_id,
            "restart_full_subtree": bool(full_subtree),
            "session_id": session_id,
            "token": token or str(uuid.uuid4()),
            "confirm_response": 1,
            "return_handler": "restart_dialog.result",
        },
        "ts": time.time(),
    })
    bus.emit("outbound.message", session_id=session_id, channel="outgoing.command", packet=packet)
