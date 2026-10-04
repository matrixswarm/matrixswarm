"""Marshal bridge calls from HTTP worker threads onto Phoenix's Qt thread."""

from __future__ import annotations

import threading
import time
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
    deadline: float = field(default_factory=lambda: time.monotonic() + 125)
    cancelled: threading.Event = field(default_factory=threading.Event)


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
            ticket.cancelled.set()
            raise TimeoutError("Phoenix did not answer the bridge request in time")
        if ticket.error is not None:
            if isinstance(ticket.error, (ValueError, PermissionError)):
                raise ticket.error
            raise RuntimeError("Phoenix could not complete the request.")
        return ticket.result or {}

    def _execute(self, ticket: _Ticket) -> None:
        try:
            if ticket.cancelled.is_set() or time.monotonic() >= ticket.deadline:
                raise TimeoutError("Request expired before dispatch.")
            ticket.result = self._backend.handle(ticket.method, ticket.params)
        except BaseException as exc:
            ticket.error = exc
        finally:
            ticket.done.set()
