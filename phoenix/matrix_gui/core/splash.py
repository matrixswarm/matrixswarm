import sys
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtGui import QPixmap, QFont, QPainter
from PyQt6.QtCore import Qt, QTimer, QRect



class PhoenixSplash(QWidget):
    def __init__(self):
        super().__init__()
        # --- window flags ---
        self.setWindowFlags(
            Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.logo = QPixmap("matrix_gui/theme/matrixswarm_logo.png")
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        max_width = min(700, int(available.width() * 0.75)) if available else 700
        self.message_height = 40
        max_height = min(700, max(1, int(available.height() * 0.75) - self.message_height)) if available else 700
        if self.logo.width() > max_width or self.logo.height() > max_height:
            self.logo = self.logo.scaled(
                max_width, max_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.setFixedSize(self.logo.width(), self.logo.height() + self.message_height)
        self.setStyleSheet("background: black;")
        self.font = QFont("Consolas", 10)

        self.text = "Establishing Trust Lineage..."
        self.messages = [
            "Decrypting Vault…",
            "Assembling Guardians…",
            "Establishing Trust Lineage…",
            "All Hail the Queen!",
        ]
        self.index = 0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_message)
        self.timer.start(1200)

    def next_message(self):
        self.index = (self.index + 1) % len(self.messages)
        self.text = self.messages[self.index]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.logo)
        painter.setFont(self.font)
        painter.setPen(Qt.GlobalColor.white)

        # The artwork already has a little empty space at its lower edge.
        # Include it when centering the message in the available black area.
        inset = min(20, int(self.logo.height() * 0.035))
        rect = QRect(0, self.logo.height() - inset, self.width(), self.message_height + inset)
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignCenter,
            self.text,
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    splash = PhoenixSplash()
    splash.show()
    QTimer.singleShot(7000, splash.close)
    sys.exit(app.exec())
