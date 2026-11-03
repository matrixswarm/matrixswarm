"""Common panel for private, attributed webpage watches."""
import time
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTextEdit, QVBoxLayout
from matrix_gui.core.panel.custom_panels.life_signal.life_signal import LifeSignal


class WorldWatchPanel(LifeSignal):
    ALLOW_CAPTCHA = False
    ALLOW_FEEDS = False

    def _build_ui(self):
        self.captures = []
        self._capture_parts = []
        self._capture_id = None
        layout = super()._build_ui()
        self.preset.hide()
        self.kind.hide()
        self.mode.hide()
        layout.addWidget(QLabel('Recent private page snapshots'))
        row = QHBoxLayout()
        self.capture_select = QComboBox()
        self.view_capture = QPushButton('View snapshot')
        self.clear_captures = QPushButton('Clear source snapshots')
        self.view_capture.clicked.connect(self._view_capture)
        self.clear_captures.clicked.connect(self._clear_captures)
        row.addWidget(self.capture_select, 1)
        row.addWidget(self.view_capture)
        row.addWidget(self.clear_captures)
        layout.addLayout(row)
        return layout

    def _receive(self, content):
        if not self._signals_connected or not self.pending or content.get('request_id') != self.pending[0]:
            return
        operation = self.pending[1]
        if operation == 'capture':
            self.pending = None
            if not content.get('ok'):
                self._busy(False)
                self.status.setText('Snapshot request rejected: ' + str(content.get('error', 'unknown error')))
                return
            offset = sum(len(part) for part in self._capture_parts)
            chunk = content.get('chunk')
            if (content.get('capture_id') != self._capture_id or content.get('offset') != offset
                    or not isinstance(chunk, str) or len(chunk) > 1500
                    or content.get('next_offset') != offset + len(chunk)
                    or type(content.get('done')) is not bool
                    or (not content['done'] and not chunk) or offset + len(chunk) > 150000):
                self._busy(False)
                self.status.setText('Invalid snapshot response.')
                return
            self._capture_parts.append(chunk)
            if not content['done']:
                self._request('capture', capture_id=self._capture_id, offset=offset + len(chunk))
                return
            self._busy(False)
            self.status.setText('Snapshot loaded.')
            dialog = QDialog(self)
            dialog.setWindowTitle('Private page snapshot')
            dialog.resize(800, 600)
            box = QVBoxLayout(dialog)
            meta = QLabel(str(content.get('url', '')) + '  |  SHA-256: ' + str(content.get('sha256', '')))
            meta.setTextFormat(Qt.TextFormat.PlainText)
            meta.setWordWrap(True)
            box.addWidget(meta)
            text = QTextEdit()
            text.setReadOnly(True)
            text.setPlainText(''.join(self._capture_parts))
            box.addWidget(text)
            dialog.exec()
            return
        super()._receive(content)
        if content.get('ok') and self.revision == content.get('revision'):
            self.captures = content.get('captures', []) if isinstance(content.get('captures'), list) else []
            self.capture_select.clear()
            names = {s['id']: s['name'] for s in self.sources}
            for item in self.captures:
                if not isinstance(item, dict) or not all(k in item for k in ('id', 'source_id', 'captured_at')):
                    continue
                try:
                    when = time.strftime('%Y-%m-%d %H:%M', time.localtime(item['captured_at']))
                except (ValueError, TypeError, OverflowError, OSError):
                    when = 'unknown time'
                self.capture_select.addItem(f"{names.get(item['source_id'], 'Deleted source')} · {when}", item)

    def _view_capture(self):
        item = self.capture_select.currentData()
        if not item or self.pending:
            self.status.setText('Select a snapshot first.')
            return
        self._capture_id = item['id']
        self._capture_parts = []
        self._request('capture', capture_id=self._capture_id, offset=0)

    def _clear_captures(self):
        item = self.capture_select.currentData()
        if not item or self.pending:
            self.status.setText('Select a snapshot first.')
            return
        if self.dirty or self.form_dirty:
            self.status.setText('Save or reload your edits before clearing history.')
            return
        if QMessageBox.question(self, 'Clear history?', 'Permanently delete all snapshots for this source?') == QMessageBox.StandardButton.Yes:
            self._request('clear_history', source_id=item['source_id'])
