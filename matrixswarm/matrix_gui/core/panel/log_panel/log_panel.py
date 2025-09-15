from PyQt5.QtWidgets import QPlainTextEdit
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtGui import QTextCharFormat, QColor
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

CHUNK_SIZE = 200

class LogPanel(QPlainTextEdit):
    line_count_changed = pyqtSignal(int)

    def __init__(self, bus, parent=None):
        super().__init__(parent)

        try:
            self.bus = bus
            self.setReadOnly(True)
            self.setFont(QFont("Courier New", 9))           # monospace
            self.setLineWrapMode(QPlainTextEdit.NoWrap)     # no wrapping

            self._line_count = 0
            self._pending_lines = []

            # timer for safe batch flush
            self._flush_timer = QTimer(self)
            self._flush_timer.timeout.connect(self._flush_lines)
        except Exception as e:
            emit_gui_exception_log("log_panel.__init__", e)

    def append_log_lines(self, lines):
        if not lines:
            return
        print(f"[LOGPANEL] Queued {len(lines)} lines")
        self._pending_lines.extend(lines)
        if not self._flush_timer.isActive():
            QTimer.singleShot(0, self._flush_lines)

    def _append_colored_line(self, line: str):
        fmt = QTextCharFormat()
        if "[ERROR]" in line:
            fmt.setForeground(QColor("red"))
        elif "[WARN" in line or "[WARNING]" in line:
            fmt.setForeground(QColor("orange"))
        elif "[INFO]" in line:
            fmt.setForeground(QColor("green"))
        else:
            fmt.setForeground(QColor("gray"))

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(line + "\n", fmt)

    def _flush_lines(self):
        if not self._pending_lines:
            return
        chunk = self._pending_lines[:CHUNK_SIZE]
        self._pending_lines = self._pending_lines[CHUNK_SIZE:]
        print(f"[LOGPANEL] Flushing {len(chunk)} lines")

        for line in chunk:
            self._append_colored_line(str(line))

        self._line_count += len(chunk)
        self.line_count_changed.emit(self._line_count)

        self.moveCursor(QTextCursor.End)
        self.ensureCursorVisible()

        if self._pending_lines:
            self._flush_timer.start(30)

    def handle_log_update(self, token, lines, paused: bool):
        try:
            if token != self.get_active_token():
                return
            if not paused:
                self.append_log_lines(lines)
        except Exception as e:
            emit_gui_exception_log("log_panel.handle_log_update", e)


    @property
    def line_count(self):
        return self._line_count

    def set_active_token(self, token: str):
        try:
            self._active_token = token
            self.clear()
            self._line_count = 0
            self.line_count_changed.emit(0)
        except Exception as e:
            emit_gui_exception_log("log_panel.set_active_token", e)



    def get_active_token(self) -> str:
        return getattr(self, "_active_token", None)