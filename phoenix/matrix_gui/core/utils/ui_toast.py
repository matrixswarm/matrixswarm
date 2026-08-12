from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtCore import QRectF


def show_toast(message="Done!", duration=3000):
    """Simple, solid toast that just appears and fades after `duration` ms."""
    app = QApplication.instance()
    print("App:", app, "closingDown:", getattr(app, "closingDown", lambda: None)())
    if not app or app.closingDown():
        print("No active QApplication — skipping toast")
        return


    class Toast(QWidget):
        _live = []

        def __init__(self, text, ms):
            super().__init__(None)
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool
            )
            #self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.setWindowModality(Qt.WindowModality.NonModal)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(20, 14, 20, 14)
            label = QLabel(text)
            label.setStyleSheet("color: white; font: 10pt 'Segoe UI';")
            layout.addWidget(label)

            self.adjustSize()
            self.move(self._corner())
            self.show()
            self.raise_()

            QTimer.singleShot(ms, self._close)
            Toast._live.append(self)

        def _corner(self):
            geo = QApplication.primaryScreen().availableGeometry()
            x = geo.right() - self.width() - 30
            y = geo.bottom() - self.height() - 40
            return QPoint(x, y)

        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), 10, 10)
            painter.fillPath(path, QColor(40, 40, 40, 230))

        def _close(self):
            self.close()
            if self in Toast._live:
                Toast._live.remove(self)

    print('Give me some Honey!')
    QTimer.singleShot(0, lambda: Toast(message, duration))


print('Give me some Jam!')