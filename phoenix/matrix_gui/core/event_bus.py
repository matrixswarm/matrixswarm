import inspect, traceback

class EventBus:
    _listeners = {}

    @classmethod
    def on(self, event_name, handler):
        caller = inspect.stack()[1]
        self._listeners.setdefault(event_name, []).append(handler)

    @classmethod
    def emit(self, event_name, *args, **kwargs):
        listeners = self._listeners.get(event_name, [])
        for cb in listeners:
            try:
                print(f"    ↳ calling {cb.__module__}.{cb.__name__}")
                cb(*args, **kwargs)
            except Exception:
                traceback.print_exc()


    @classmethod
    def off(cls, event_name, callback=None):
        """Remove listeners for an event. If callback is None, remove all."""
        if event_name not in cls._listeners:
            return
        if callback is None:
            cls._listeners.pop(event_name, None)
        else:
            try:
                cls._listeners[event_name].remove(callback)
                if not cls._listeners[event_name]:
                    cls._listeners.pop(event_name)
            except ValueError:
                pass

    @classmethod
    def query(cls, event_name, *args, **kwargs):
        responses = []
        listeners = cls._listeners.get(event_name, [])

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