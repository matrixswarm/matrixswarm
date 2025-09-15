from matrix_gui.core.event_bus import EventBus

class SessionBus(EventBus):
    """
    A scoped EventBus instance, isolated per session_id.
    """
    def __init__(self, session_id):
        super().__init__()
        self.session_id = session_id
        self.stamp = f"BUS[{session_id[:8]}]"  # short stamp for logs
