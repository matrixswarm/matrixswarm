"""Short-lived, local-only QR display for a retrieved text item."""
import math
import time

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from matrix_gui.core.event_bus import EventBus

MAX_QR_BYTES = 512
QR_LIFETIME_SECONDS = 60


def text_pixmap(data):
    """Render exact UTF-8 text without files, clipboard or image services."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_QR_BYTES:
        raise ValueError("QR text must contain 1–512 UTF-8 bytes.")
    text = data.decode("utf-8")
    # Lazy import keeps the rest of Drop Vault usable before dependencies update.
    import segno

    code = segno.make_qr(text, mode="byte", encoding="utf-8", eci=True, error="m")
    side = len(code.matrix) + 8  # Four white modules on every edge.
    scale = max(4, min(12, 420 // side))
    image = QImage(side * scale, side * scale, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    try:
        for y, row in enumerate(code.matrix):
            for x, dark in enumerate(row):
                if dark:
                    painter.fillRect((x + 4) * scale, (y + 4) * scale,
                                     scale, scale, Qt.GlobalColor.black)
    finally:
        painter.end()
    return QPixmap.fromImage(image)


class TextQrDialog(QDialog):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Drop Vault · Scan text")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        hint = QLabel("Scan with your Android camera or trusted QR reader.")
        hint.setWordWrap(True)
        hint.setMaximumWidth(480)
        layout.addWidget(hint)
        self.code_image = QLabel()
        self.code_image.setStyleSheet(
            "background: white; border: none; border-radius: 0; padding: 0; margin: 0;")
        self.code_image.setPixmap(text_pixmap(data))
        self.code_image.setFixedSize(self.code_image.pixmap().size())
        layout.addWidget(self.code_image, alignment=Qt.AlignmentFlag.AlignHCenter)
        notice = QLabel("Anyone who scans this code can read the text. "
                        "Hiding it does not erase a photo or your phone's scan history.")
        notice.setWordWrap(True)
        notice.setMaximumWidth(480)
        layout.addWidget(notice)
        self.countdown = QLabel()
        layout.addWidget(self.countdown)
        hide = QPushButton("Hide QR")
        hide.clicked.connect(self.reject)
        layout.addWidget(hide)
        self._deadline = time.monotonic() + QR_LIFETIME_SECONDS
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)
        self._tick()

    def exec(self):
        EventBus.on("vault.closed", self._vault_closed)
        self._timer.start()
        try:
            return super().exec()
        finally:
            EventBus.off("vault.closed", self._vault_closed)
            self._clear_code()

    def _tick(self):
        remaining = max(0, math.ceil(self._deadline - time.monotonic()))
        self.countdown.setText(f"Hides in {remaining} seconds")
        if remaining == 0:
            self.reject()

    def _vault_closed(self, **_):
        self.reject()

    def _clear_code(self):
        self._timer.stop()
        self.code_image.clear()

    def done(self, result):
        self._clear_code()
        super().done(result)

    def hideEvent(self, event):
        self._clear_code()
        super().hideEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            self.reject()
        super().changeEvent(event)
