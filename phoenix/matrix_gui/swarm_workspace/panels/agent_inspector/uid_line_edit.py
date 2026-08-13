from PyQt6.QtWidgets import (QLineEdit)
from PyQt6.QtCore import Qt
class UIDLineEdit(QLineEdit):
    def __init__(self, validate_fn, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._validate_fn = validate_fn

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if self._validate_fn:
            self._validate_fn()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._validate_fn:
                self._validate_fn()
            event.accept()  # Prevent default button triggers (like Deploy)
        else:
            super().keyPressEvent(event)