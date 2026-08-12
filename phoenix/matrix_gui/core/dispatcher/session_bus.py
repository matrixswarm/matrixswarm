from threading import RLock
import traceback

class SessionBus:
    """
    A fully isolated event bus per session_id.
    Prevents cross-session bleed and stale callback crashes.
    """
    def __init__(self, session_id):
        self.session_id = session_id
        self._listeners = {}
        self._lock = RLock()

    def on(self, event_name, handler):
        """Register a callback for an event."""
        self._listeners.setdefault(event_name, []).append(handler)

    def emit(self, event_name, *args, **kwargs):
        with self._lock:
            listeners = list(self._listeners.get(event_name, []))
        for cb in listeners:
            try:
                cb(*args, **kwargs)
            except Exception:
                traceback.print_exc()

    def off(self, event_name, callback=None):
        """Remove listeners from this bus only."""
        if event_name not in self._listeners:
            return
        if callback is None:
            self._listeners.pop(event_name, None)
        else:
            try:
                self._listeners[event_name].remove(callback)
                if not self._listeners[event_name]:
                    self._listeners.pop(event_name)
            except ValueError:
                pass

    def clear(self):
        """Completely clear this bus."""
        self._listeners.clear()