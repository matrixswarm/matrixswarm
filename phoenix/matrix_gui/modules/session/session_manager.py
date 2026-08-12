from __future__ import annotations
import uuid
from matrix_gui.core.event_bus import EventBus
from dataclasses import dataclass, field
from queue import Queue

@dataclass
class SessionContext:
    id: str
    group: object
    outq: Queue = field(default_factory=Queue)
    channels: dict = field(default_factory=dict)   # {"https": conn, "wss-main": ws, "wss-logs": ws}
    status: dict = field(default_factory=dict)     # {"wss-main": "connected", "wss-logs": "retrying"}

class SessionManager:
    def __init__(self, bus):
        self.bus = bus
        self._by_id: dict[str, SessionContext] = {}

    def create(self, group) -> SessionContext:
        sid = group.get("id")
        if not sid:
            sid = str(uuid.uuid4())
            group["id"] = sid

        ctx = SessionContext(id=sid, group=group)
        self._by_id[sid] = ctx

        gname = group.get("name", "?")
        print(f"[SESSION] created: {sid} for {gname}")
        self.bus.emit("session.opened", session_id=sid, group=group)
        return ctx

    def get(self, sid: str) -> SessionContext | None:
        return self._by_id.get(sid)

    def destroy(self, sid: str) -> None:
        ctx = self._by_id.pop(sid, None)
        if ctx:
            self.bus.emit("session.closed", session_id=sid)

sessions = SessionManager(EventBus)