class EventBus:
    _listeners = {}

    @classmethod
    def on(cls, event_name, callback):
        cls._listeners.setdefault(event_name, []).append(callback)
        cls._listeners[event_name].sort(key=lambda x: getattr(x, '__priority__', 100))

    @classmethod
    def emit(cls, event_name, *args, **kwargs):
        listeners = cls._listeners.get(event_name, [])
        print(f"[EVENT] {event_name} fired → {len(listeners)} listeners")
        for cb in listeners:
            try:
                cb(*args, **kwargs)
            except Exception as e:
                print(f"[EVENT ERROR] Listener on '{event_name}' failed: {e}")

    @classmethod
    def query(cls, event_name, *args, **kwargs):
        responses = []
        listeners = cls._listeners.get(event_name, [])
        print(f"[QUERY] {event_name} queried → {len(listeners)} listeners")
        for cb in listeners:
            try:
                result = cb(*args, **kwargs)
                if result is not None:
                    responses.append(result)
            except Exception as e:
                print(f"[QUERY ERROR] {event_name} listener failed: {e}")
        return responses

    @classmethod
    def clear(cls):
        cls._listeners.clear()

# Global registry of all live session containers
SessionRegistry = {}  # session_id → SessionContainer