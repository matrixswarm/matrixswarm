from matrix_gui.modules.session.session_manager import SessionManager
from matrix_gui.core.event_bus import EventBus as EventBusClass

_sessions = None

def get_sessions():
    global _sessions
    if _sessions is None:
        print("[DEBUG] Initializing global session manager")

        try:
            _sessions = SessionManager(EventBusClass())   # ← create a real instance
        except Exception as e:
            print("[ERROR] Failed to initialize SessionManager:", e)
            return None

    return _sessions
