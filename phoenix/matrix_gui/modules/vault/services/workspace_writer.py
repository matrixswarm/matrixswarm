"""One disk writer; completion is marshalled back to the Qt owner thread."""
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, Qt


_WRITER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="phoenix-vault")


class WorkspaceWriter(QObject):
    completed = pyqtSignal(object)

    def __init__(self, callback):
        super().__init__()
        self._callback = callback
        self.completed.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    @pyqtSlot(object)
    def _deliver(self, error):
        self._callback(error)

    def submit(self, snapshot, password, path):
        # Import inside the worker: no Qt or EventBus callbacks run there.
        def write():
            from .vault_service_loader import save_vault_singlefile
            save_vault_singlefile(snapshot, password, path)
        future = _WRITER.submit(write)
        future.add_done_callback(lambda done: self.completed.emit(done.exception()))
