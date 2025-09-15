class ConnectorBus:
    """
    Dedicated event bus for raw connector traffic per session.
    Isolated from SessionBus and EventBus.
    """
    _buses = {}  # session_id → ConnectorBus

    def __init__(self, session_id):
        self.session_id = session_id
        self._listeners = {}

    def on(self, event, callback):
        self._listeners.setdefault(event, []).append(callback)

    def off(self, event, callback):
        if event in self._listeners:
            try:
                self._listeners[event].remove(callback)
                if not self._listeners[event]:
                    del self._listeners[event]
                print(f"[CONN-BUS[{self.session_id[:8]}]] ❌ OFF {event} → {callback.__name__}")
            except ValueError:
                pass

    def emit(self, event, *args, **kwargs):
        listeners = self._listeners.get(event, [])
        print(f"[CONN-BUS[{self.session_id[:8]}]] 🔊 EMIT {event} → {len(listeners)}")
        for cb in listeners:
            try:
                cb(*args, **kwargs)
            except Exception as e:
                print(f"[CONN-BUS[{self.session_id[:8]}]] ⚠️ Handler error: {e}")

    @classmethod
    def get(cls, session_id):
        if session_id not in cls._buses:
            cls._buses[session_id] = ConnectorBus(session_id)
        return cls._buses[session_id]
