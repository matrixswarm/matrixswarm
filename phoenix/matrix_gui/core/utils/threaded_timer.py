from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

class ThreadedTimer(QObject):
    tick = pyqtSignal()

    def __init__(self, interval_ms=100, parent=None):
        super().__init__(parent)
        self._thread = QThread()
        self.moveToThread(self._thread)
        self.timer = QTimer()
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.tick.emit)
        self.timer.moveToThread(self._thread)
        self._thread.started.connect(self.timer.start)
        self._thread.start()

    def stop(self):
        self.timer.stop()
        self._thread.quit()
        self._thread.wait()
