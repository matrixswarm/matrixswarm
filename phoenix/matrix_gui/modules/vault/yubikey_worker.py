"""Non-blocking Qt worker for Phoenix YubiKey vault operations."""

from threading import Event

from PyQt6.QtCore import QThread, pyqtSignal

from .crypto.yubikey_factor import request_yubikey_credential


class YubiKeyCredentialWorker(QThread):
    credential_ready = pyqtSignal(str, object)
    failed = pyqtSignal(str)
    touch_requested = pyqtSignal()

    def __init__(self, secondary_word: str, parent=None):
        super().__init__(parent)
        self._secondary_word = secondary_word
        self._cancel_event = Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        try:
            credential = request_yubikey_credential(
                self._secondary_word,
                cancellation_event=self._cancel_event,
                touch_callback=self.touch_requested.emit,
            )
        except Exception as exc:
            if not self._cancel_event.is_set():
                self.failed.emit(str(exc))
            return

        if not self._cancel_event.is_set():
            self.credential_ready.emit(credential.password, credential.serial)
