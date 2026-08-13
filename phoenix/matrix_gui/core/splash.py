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
        self.setFixedSize(self.logo.width(), self.logo.height())
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

        text_y = self.height() - 30
        rect = QRect(0, text_y, self.width(), 60)
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            self.text,
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    splash = PhoenixSplash()
    splash.show()
    QTimer.singleShot(7000, splash.close)
    sys.exit(app.exec())
