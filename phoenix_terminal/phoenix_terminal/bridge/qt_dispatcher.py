"""Marshal bridge calls from HTTP worker threads onto Phoenix's Qt thread."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from PyQt6.QtCore import QObject, Qt, pyqtSignal


@dataclass
class _Ticket:
    method: str
    params: dict[str, Any]
    done: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None
    error: BaseException | None = None


class QtBridgeDispatcher(QObject):
    requested = pyqtSignal(object)

    def __init__(self, backend: object):
        super().__init__()
        self._backend = backend
        self.requested.connect(self._execute, Qt.ConnectionType.QueuedConnection)

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        ticket = _Ticket(method=method, params=params)
        self.requested.emit(ticket)
        if not ticket.done.wait(timeout=125):
            raise TimeoutError("Phoenix did not answer the bridge request in time")
        if ticket.error is not None:
            raise RuntimeError(str(ticket.error))
        return ticket.result or {}

    def _execute(self, ticket: _Ticket) -> None:
        try:
            ticket.result = self._backend.handle(ticket.method, ticket.params)
        except BaseException as exc:
            ticket.error = exc
        finally:
            ticket.done.set()
