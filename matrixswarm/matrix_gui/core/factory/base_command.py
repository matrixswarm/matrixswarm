from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.event_bus import EventBus

class BaseCommand:
    def __init__(self, sid, conn, bus):
        self.sid = sid
        self.conn = conn
        self.bus = bus
        self.listeners = []

    def add_listener(self, event_name, callback):
        self.bus.on(event_name, callback)
        self.listeners.append((event_name, callback))

    def remove_listeners(self):
        for event, cb in self.listeners:
            try:
                self.bus.off(event, cb)
            except Exception as e:
                print(f"[BaseCommand][WARN] Failed to off {event}: {e}")
        self.listeners.clear()

    def send(self, payload, channel_role="outgoing.command", target_uid=None):
        print(f"[{self.__class__.__name__}] 📨 Routed cmd → {channel_role} "
              f"(sid={self.sid}, bus={getattr(self.bus, 'stamp', 'GLOBAL')})")
        self.bus.emit("outbound.message",
                      session_id=self.sid,
                      channel=channel_role,
                      payload=payload)
        print(f"[{self.__class__.__name__}] 📨 Routed cmd → {channel_role}")

    def initialize(self):
        """Override to subscribe to EventBus events"""
        raise NotImplementedError

    def fire_event(self, **kwargs):
        """Override to build outbound Matrix payload"""
        raise NotImplementedError

    def off_event(self):
        self.remove_listeners()
        print(f"[Command][{self.__class__.__name__}] Unsubscribed for {self.sid}")