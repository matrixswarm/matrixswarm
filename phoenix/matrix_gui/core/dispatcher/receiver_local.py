from matrix_gui.core.dispatcher.inbound_dispatcher import InboundDispatcher
from matrix_gui.core.dispatcher.outbound_dispatcher import OutboundDispatcher
from matrix_gui.config.boot.globals import get_sessions

def initialize_session_dispatchers(session_id, bus, vault_data=None):
    sessions = get_sessions()
    inbound = InboundDispatcher(session_id, bus)
    outbound = OutboundDispatcher(session_id, bus, sessions, vault_data or {})
    print(f"[SESSION_RECEIVER] Dispatchers created for {session_id} (detached)")
    return inbound, outbound