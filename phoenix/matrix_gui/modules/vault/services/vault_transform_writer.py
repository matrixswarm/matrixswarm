"""Run one detached vault transform and atomic save off the Qt thread."""
from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot

from .workspace_writer import _WRITER
import json
from copy import deepcopy


class VaultTransformWriter(QObject):
    completed = pyqtSignal(object, object, object)

    def __init__(self, callback):
        super().__init__()
        self._callback = callback
        self.completed.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    @pyqtSlot(object, object, object)
    def _deliver(self, result, candidate, error):
        self._callback(result, candidate, error)

    def submit(self, snapshot, password, path, section, transform):
        def write():
            from .vault_service_loader import save_vault_singlefile
            deployments = snapshot.get("deployments", {})
            if not isinstance(deployments, dict) or any(not isinstance(value, dict) for value in deployments.values()):
                raise ValueError("Vault deployments section is malformed")
            replacement, result = transform(snapshot.get(section, {}))
            if replacement is None:
                raise ValueError("A vault section cannot be removed by a transform")
            # Detach before touching disk: an allocation failure after the
            # atomic replace must not be misreported as a failed save.
            candidate = deepcopy(replacement)
            snapshot[section] = candidate
            if len(json.dumps(snapshot)) < 200:
                raise ValueError("Refusing to shrink vault unnaturally")
            last_good = deepcopy(snapshot)
            save_vault_singlefile(snapshot, password, path)
            return result, (candidate, last_good)

        future = _WRITER.submit(write)
        def finished(done):
            try:
                result, candidate = done.result()
            except Exception as exc:
                self.completed.emit(None, None, exc)
            else:
                self.completed.emit(result, candidate, None)
        future.add_done_callback(finished)
