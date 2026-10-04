"""Bounded file I/O outside the GUI thread; no implicit plaintext cache."""
import hashlib
import os
from pathlib import Path
import stat
import tempfile
import threading
from PyQt6.QtCore import QObject, pyqtSignal

MAX_BYTES = 1024 * 1024
_WORKERS = set()  # Running jobs outlive a closed panel safely.


class FileJob(QObject):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, mode, path, data=None):
        super().__init__()
        self.mode, self.path, self.data = mode, str(path), data

    def run(self):
        try:
            if self.mode == "read":
                descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
                with os.fdopen(descriptor, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                        raise ValueError("Choose a regular file no larger than 1 MiB")
                    data = stream.read(MAX_BYTES + 1)
                    if len(data) > MAX_BYTES:
                        raise ValueError("File grew beyond the 1 MiB limit")
                    after = os.fstat(stream.fileno())
                    if (after.st_size, after.st_mtime_ns) != (info.st_size, info.st_mtime_ns):
                        raise ValueError("File changed while being read; retry after saving it")
                self.completed.emit({"data": data, "filename": Path(self.path).name,
                                     "sha256": hashlib.sha256(data).hexdigest()})
            else:
                target = Path(self.path)
                descriptor, temp = tempfile.mkstemp(prefix=".drop-export-", dir=target.parent)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        os.chmod(temp, 0o600)
                        stream.write(self.data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temp, target)
                finally:
                    if os.path.exists(temp):
                        os.unlink(temp)
                self.completed.emit({"path": str(target)})
        except Exception as exc:
            # Never echo paths, OS error messages or file contents into logs.
            self.failed.emit(f"Local file operation failed ({type(exc).__name__}); the transfer was not completed.")
        finally:
            self.data = None
            self.finished.emit()

    def launch(self):
        _WORKERS.add(self)
        self.finished.connect(self._finished)
        # A slow local/network filesystem must not destroy a running QThread
        # when the cockpit exits. The worker touches no widgets; only queued
        # Qt signals cross back to the main thread. Explicit exports may still
        # finish after panel close (or be interrupted by process exit).
        threading.Thread(target=self.run, name="drop-vault-file-io", daemon=True).start()

    def _finished(self):
        _WORKERS.discard(self)
        self.deleteLater()
