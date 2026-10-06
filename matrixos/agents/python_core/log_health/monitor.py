"""Bounded, in-memory log tailing. Never changes filesystem permissions."""
import errno
import json
import os
import stat
import threading
import time
import uuid
from collections import deque


class LogMonitor:
    MAX_LINE_BYTES = 1024
    MAX_BATCH_BYTES = 65536
    MAX_BATCH_LINES = 100

    def __init__(self, path, rules):
        self.path = path
        self.rules = rules
        self.lock = threading.RLock()
        self.stream = uuid.uuid4().hex
        self.events = deque(maxlen=500)
        self.sequence = 0
        self.state = "starting"
        self.last_read = None
        self.last_event = None
        self.rotations = 0
        self._file = None
        self._opened_once = False
        self._partial = b""
        self._truncated = False

    @staticmethod
    def _error(exc):
        if isinstance(exc, PermissionError):
            return "denied"
        if isinstance(exc, FileNotFoundError):
            return "missing"
        if isinstance(exc, ValueError) or getattr(exc, "errno", None) == errno.ELOOP:
            return "invalid path"
        return "read error"

    def _open(self):
        # O_NONBLOCK also prevents a replaced FIFO from blocking between stat
        # and open. Only the configured regular file may be read.
        if not isinstance(self.path, str) or not os.path.isabs(self.path):
            raise ValueError("An absolute configured path is required")
        if not stat.S_ISREG(os.stat(self.path, follow_symlinks=False).st_mode):
            raise ValueError("A regular file is required")
        fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
                     | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("A regular file is required")
            return os.fdopen(fd, "rb", buffering=8192)
        except Exception:
            os.close(fd)
            raise

    def check_access(self):
        try:
            with self._open():
                pass
            result = "readable"
        except (OSError, ValueError) as exc:
            result = self._error(exc)
        return {"result": result, "checked_at": time.time()}

    def _append(self, raw, truncated=False):
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            return None
        severity = "INFO"
        for level, keywords in self.rules.items():
            if any(word.lower() in line.lower() for word in keywords):
                severity = level
                break
        self.sequence += 1
        self.last_event = time.time()
        event = {"id": self.sequence, "time": self.last_event, "severity": severity,
                 "text": line, "truncated": truncated}
        self.events.append(event)
        return event

    def _drain(self):
        result = []
        consumed = 0
        eof = False
        while consumed < self.MAX_BATCH_BYTES and len(result) < self.MAX_BATCH_LINES:
            raw = self._file.readline(min(4096, self.MAX_BATCH_BYTES - consumed))
            if not raw:
                eof = True
                break
            consumed += len(raw)
            room = self.MAX_LINE_BYTES - len(self._partial)
            self._partial += raw[:room]
            self._truncated |= len(raw) > room
            if raw.endswith(b"\n"):
                event = self._append(self._partial, self._truncated)
                self._partial, self._truncated = b"", False
                if event:
                    result.append(event)
        return result, eof

    def poll(self):
        with self.lock:
            try:
                if self._file is None:
                    self._file = self._open()
                    if not self._opened_once:
                        self._file.seek(0, os.SEEK_END)
                    self._opened_once = True
                current = os.stat(self.path, follow_symlinks=False)
                if not stat.S_ISREG(current.st_mode):
                    raise ValueError("A regular file is required")
                opened = os.fstat(self._file.fileno())
                replaced = (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)
                if not replaced and current.st_size < self._file.tell():
                    self._file.seek(0)
                    self._partial, self._truncated = b"", False
                    self.rotations += 1
                events, eof = self._drain()
                if replaced and eof:
                    # Drain the old handle before following the replacement on
                    # the next cycle; include its final unterminated line.
                    if self._partial:
                        event = self._append(self._partial, self._truncated)
                        if event:
                            events.append(event)
                    self.close()
                    self.rotations += 1
                self.last_read = time.time()
                self.state = "watching" if events else "quiet"
                return events
            except (OSError, ValueError) as exc:
                self.state = self._error(exc)
                # Keep the cursor across a temporary permission/path failure.
                return []

    def snapshot(self, cursor=0, stream=None):
        with self.lock:
            oldest = self.events[0]["id"] if self.events else self.sequence + 1
            reset = stream != self.stream or cursor > self.sequence
            start = max(oldest - 1, self.sequence - 40) if reset else max(cursor, oldest - 1)
            snapshot = {"stream": self.stream, "state": self.state,
                        "last_read": self.last_read, "last_event": self.last_event,
                        "rotations": self.rotations, "events": [], "cursor": start,
                        "reset": reset, "skipped": max(0, start - (0 if reset else cursor)),
                        "more": False}
            # Leave room for callback metadata, JSON escaping and encryption.
            size = 0
            for event in self.events:
                if event["id"] <= start:
                    continue
                encoded = len(json.dumps(event, ensure_ascii=True).encode("ascii"))
                if snapshot["events"] and size + encoded > 6000:
                    break
                snapshot["events"].append(dict(event))
                snapshot["cursor"] = event["id"]
                size += encoded
                if len(snapshot["events"]) >= 40:
                    break
            snapshot["more"] = snapshot["cursor"] < self.sequence
            return snapshot

    def close(self):
        with self.lock:
            if self._file is not None:
                self._file.close()
                self._file = None
            self._partial, self._truncated = b"", False
