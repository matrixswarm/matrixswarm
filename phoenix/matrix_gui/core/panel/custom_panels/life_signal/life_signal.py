"""Phoenix source and keyword editor for LifeSignal."""
from copy import deepcopy
import time
from urllib.parse import urlsplit
from uuid import uuid4

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.class_lib.packet_delivery.utility.security.packet_size import guard_packet_size


class LifeSignal(PhoenixPanelInterface):
    cache_panel = True
    received = pyqtSignal(object)
    DISPLAY_NAME = 'LifeSignal'
    ICON = '📡'
    SERVICE_PREFIX = 'hive.life_signal.'
    REPLY_EVENT = 'inbound.verified.life_signal.config'
    ALLOW_CAPTCHA = True
    ALLOW_FEEDS = True
    HELP_TEXT = ('Watch permitted sources. Change monitoring establishes a baseline before sending alerts. '
        'CAPTCHA monitoring sends page text to Oracle on each check and may incur API charges. '
        'Detected challenges pause the source until you re-enable it.')

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self.agent_uid = (node or {}).get('universal_id')
        self.token = uuid4().hex
        self.sources, self.blocked, self.events, self.observations = [], {}, [], {}
        self.analysis_errors = {}
        self.pending_counts = {}
        self.revision = None
        self.current_id = None
        self.pending = None
        self.dirty = False
        self.form_dirty = False
        self._populating = False
        self._signals_connected = False
        self.setLayout(self._build_ui())
        self.received.connect(self._receive)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self._timers.append(self.timer)
        self._busy(False)

    def _build_ui(self):
        layout = QVBoxLayout()
        title = QLabel(f'{self.ICON} {self.DISPLAY_NAME} · Provisional — QC testing needed')
        title.setStyleSheet('font-size: 20px; font-weight: bold;')
        layout.addWidget(title)
        help_text = QLabel(self.HELP_TEXT)
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.status = QLabel('Open this panel to load sources.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Source', 'Type', 'Status'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._selected)
        split.addWidget(self.table)
        self.editor = QWidget()
        form = QFormLayout(self.editor)
        self.name = QLineEdit()
        self.preset = QComboBox()
        self.preset.addItem('Choose a starter…', None)
        for preset in ((self.node or {}).get('config', {}).get('source_presets', [])):
            if isinstance(preset, dict) and preset.get('kind') in ('wikipedia', 'rss'):
                if self.ALLOW_FEEDS or preset.get('kind') == 'page':
                    self.preset.addItem(preset.get('name', 'Wikipedia biography'), preset)
        self.preset.currentIndexChanged.connect(self._preset_selected)
        self.url = QLineEdit()
        self.url.setPlaceholderText('https://…')
        self.kind = QComboBox()
        self.kind.addItem('Webpage', 'page')
        if self.ALLOW_FEEDS:
            self.kind.addItem('RSS / Atom feed', 'rss')
            self.kind.addItem('Wikipedia article (live changes)', 'wikipedia')
        self.mode = QComboBox()
        self.mode.addItem('Watch for reported changes', 'changes')
        if self.ALLOW_CAPTCHA:
            self.mode.addItem('Check page for CAPTCHA with Oracle', 'captcha')
        self.mode.setToolTip('CAPTCHA mode sends the page text to Oracle on each check and may incur API charges.')
        self.keywords = QTextEdit()
        self.keywords.setPlaceholderText('One name or keyword per line')
        self.keywords.setMaximumHeight(120)
        self.interval = QSpinBox()
        self.interval.setRange(120, 86400)
        self.interval.setValue(3600)
        self.interval.setSuffix(' seconds')
        self.interval.setToolTip('Allowed range: 120 to 86400 seconds. Wikipedia uses live changes after its first check.')
        self.role = QLineEdit('hive.alert')
        self.enabled = QCheckBox('Enabled')
        self.enabled.setChecked(True)
        rows = [('Name', self.name), ('URL', self.url)]
        if self.ALLOW_FEEDS:
            rows.insert(0, ('Starter', self.preset))
            rows.append(('Source type', self.kind))
        if self.ALLOW_CAPTCHA:
            rows.append(('Analysis', self.mode))
        rows.extend([('Keywords', self.keywords), ('Poll interval', self.interval),
                     ('Alert to role', self.role), ('', self.enabled)])
        for label, widget in rows:
            form.addRow(label, widget)
        self.apply_button = QPushButton('Add / Update Draft')
        self.apply_button.clicked.connect(self._apply)
        form.addRow(self.apply_button)
        split.addWidget(self.editor)
        layout.addWidget(split, 1)
        row = QHBoxLayout()
        self.new_button = QPushButton('New')
        self.delete_button = QPushButton('Delete')
        self.reload_button = QPushButton('Reload Saved')
        self.save_button = QPushButton('Save Changes')
        self.resume_button = QPushButton('Review / Re-enable Source')
        self.retry_button = QPushButton('Retry Analysis')
        for button, handler in [(self.new_button, self._new), (self.delete_button, self._delete),
                (self.reload_button, self._reload), (self.save_button, self._save), (self.resume_button, self._resume),
                (self.retry_button, self._retry)]:
            button.clicked.connect(handler)
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(QLabel('Recent reported matches'))
        self.events_table = QTableWidget(0, 4)
        self.events_table.setHorizontalHeaderLabels(['Source', 'Title', 'Summary', 'Link'])
        self.events_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.events_table.horizontalHeader().setStretchLastSection(True)
        self.events_table.setMaximumHeight(180)
        layout.addWidget(self.events_table)
        for signal in (self.name.textChanged, self.url.textChanged, self.kind.currentIndexChanged, self.mode.currentIndexChanged,
                       self.keywords.textChanged, self.interval.valueChanged, self.role.textChanged,
                       self.enabled.stateChanged):
            signal.connect(self._changed)
        return layout

    def _busy(self, busy):
        ready = self.revision is not None and not busy
        for widget in (self.table, self.editor, self.new_button, self.delete_button, self.save_button, self.resume_button, self.retry_button):
            widget.setEnabled(ready)
        self.reload_button.setEnabled(not busy)

    def _changed(self, *_):
        if not self._populating:
            self.form_dirty = True
            self.status.setText('Unsaved form edit — Save Changes to activate it.')

    def _preset_selected(self, *_):
        preset = self.preset.currentData()
        if not isinstance(preset, dict):
            return
        self.kind.setCurrentIndex(max(0, self.kind.findData(preset['kind'])))
        self.name.setText(preset.get('name', 'Wikipedia biography'))
        self.url.setText(preset.get('url', ''))
        self.url.setFocus()
        self.status.setText('Complete the starter URL, enter keywords, then save. ' + preset.get('description', ''))

    def _clear(self):
        self._populating = True
        self.current_id = None
        self.name.clear(); self.url.clear(); self.keywords.clear()
        self.kind.setCurrentIndex(0); self.mode.setCurrentIndex(0); self.interval.setValue(3600)
        self.role.setText('hive.alert'); self.enabled.setChecked(True)
        self.form_dirty = False
        self._populating = False

    def _discard(self):
        return not self.form_dirty or QMessageBox.question(self, 'Discard edits?',
            'Discard the current unsaved form?') == QMessageBox.StandardButton.Yes

    def _new(self):
        if self._discard():
            self.table.blockSignals(True); self.table.clearSelection(); self.table.blockSignals(False)
            self._clear()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self.sources):
            return
        source = self.sources[rows[0].row()]
        if source['id'] == self.current_id:
            return
        if not self._discard():
            self.table.blockSignals(True)
            for i, item in enumerate(self.sources):
                if item['id'] == self.current_id:
                    self.table.selectRow(i)
                    break
            self.table.blockSignals(False)
            return
        self._populating = True
        self.current_id = source['id']
        self.name.setText(source['name']); self.url.setText(source['url'])
        self.kind.setCurrentIndex(max(0, self.kind.findData(source['kind'])))
        self.mode.setCurrentIndex(max(0, self.mode.findData(source.get('analysis_mode', 'changes'))))
        self.keywords.setPlainText('\n'.join(source['keywords']))
        self.interval.setValue(source['interval_sec']); self.role.setText(source['alert_role'])
        self.enabled.setChecked(source['enabled'])
        self.form_dirty = False
        self._populating = False

    def _apply(self):
        keywords = [s.strip() for s in self.keywords.toPlainText().splitlines() if s.strip()]
        if (not self.name.text().strip() or not self.url.text().startswith('https://')
                or (self.mode.currentData() == 'changes' and not keywords) or not self.role.text().strip()):
            self.status.setText('Enter a name, HTTPS URL, alert role, and keywords for change monitoring.')
            return False
        if self.mode.currentData() == 'captcha' and self.kind.currentData() != 'page':
            self.status.setText('CAPTCHA monitoring requires the Webpage source type.')
            return False
        source = {'id': self.current_id or uuid4().hex, 'name': self.name.text().strip(),
            'url': self.url.text().strip(), 'kind': self.kind.currentData(), 'keywords': keywords,
            'analysis_mode': self.mode.currentData(),
            'interval_sec': self.interval.value(), 'alert_role': self.role.text().strip(), 'enabled': self.enabled.isChecked()}
        index = next((i for i, item in enumerate(self.sources) if item['id'] == source['id']), None)
        if index is None:
            self.sources.append(source); index = len(self.sources) - 1
        else:
            self.sources[index] = source
        self.current_id = source['id']; self.form_dirty = False; self.dirty = True
        self._render(index)
        self.status.setText('Source added to draft — Save Changes to activate it.')
        return True

    def _delete(self):
        if self.current_id and self._discard():
            self.sources = [s for s in self.sources if s['id'] != self.current_id]
            self._clear(); self.dirty = True; self._render()
            self.status.setText('Source removed from draft — Save Changes to apply.')

    def _render(self, selected=None):
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.setRowCount(len(self.sources))
        for i, source in enumerate(self.sources):
            host = urlsplit(source['url']).hostname or ''
            observation = self.observations.get(source['id'], {})
            error = next((item['error'] for item in self.analysis_errors.values() if item.get('source_id') == source['id']),
                         observation.get('error'))
            baseline_ready = observation.get('baseline_ready', bool(observation.get('digest')))
            if host in self.blocked:
                state = 'Paused: access challenge'
            elif not source['enabled']:
                state = 'Disabled'
            elif error:
                state = 'Error: ' + str(error)
            elif not baseline_ready:
                state = 'Waiting for first successful check'
            else:
                checked = observation.get('last_success_at', observation.get('checked_at'))
                try:
                    when = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(checked))
                except (TypeError, ValueError, OverflowError, OSError):
                    when = 'time unavailable'
                count = self.pending_counts.get(source['id'], 0)
                state = f'Checked {when} (local)' + (f' · {count} awaiting Oracle' if count else '')
                if source.get('analysis_mode') == 'captcha':
                    result = observation.get('captcha_status')
                    label = {'yes': 'last Oracle result: possible CAPTCHA', 'no': 'last Oracle result: no CAPTCHA reported',
                             'uncertain': 'last Oracle result: inconclusive'}.get(result, 'awaiting first CAPTCHA analysis')
                    state += f' · {label}'
            for col, value in enumerate((source['name'], source['kind'], state)):
                item = QTableWidgetItem(value)
                if col == 2:
                    detail = observation.get('captcha_summary', '')
                    reason = self.blocked.get(host, {}).get('reason', '')
                    item.setToolTip('\n'.join(str(part) for part in (value, reason, detail) if part))
                self.table.setItem(i, col, item)
        if selected is not None:
            self.table.selectRow(selected)
        self.table.blockSignals(False)
        self.events_table.setRowCount(len(self.events))
        for i, event in enumerate(self.events):
            for col, key in enumerate(('source', 'title', 'summary', 'url')):
                self.events_table.setItem(i, col, QTableWidgetItem(str(event.get(key, ''))))

    def _request(self, operation, **extra):
        if self.pending:
            return
        request_id = uuid4().hex
        self.pending = (request_id, operation, time.monotonic())
        self._busy(True)
        payload = dict(extra, target_universal_id=self.agent_uid, session_id=self.session_id,
                       token=self.token, request_id=request_id)
        packet = Packet()
        packet.set_data({'handler': 'cmd_service_request', 'ts': time.time(), 'content':
            {'service': self.SERVICE_PREFIX + operation, 'payload': payload}})
        if not guard_packet_size(packet.get_packet(), log=lambda *_: None):
            self.pending = None; self._busy(False)
            self.status.setText('Configuration exceeds the control packet limit; reduce the number of sources or keywords.')
            return
        try:
            self.bus.emit('outbound.message', session_id=self.session_id, channel='outgoing.command', packet=packet)
            self.status.setText(f'Waiting for {self.DISPLAY_NAME}…')
        except Exception:
            self.pending = None; self._busy(False)
            self.status.setText('Request could not be sent; your draft is preserved.')

    def _save(self):
        if self.form_dirty and not self._apply():
            return
        self._request('update', revision=self.revision, sources=deepcopy(self.sources))

    def _reload(self):
        if (self.dirty or self.form_dirty) and QMessageBox.question(self, 'Reload Saved',
                'Discard unsaved source edits?') != QMessageBox.StandardButton.Yes:
            return
        self._request('get')

    def _resume(self):
        source = next((s for s in self.sources if s['id'] == self.current_id), None)
        host = urlsplit(source['url']).hostname if source else None
        if not host or host not in self.blocked:
            self.status.setText('Select a paused source first.')
            return
        if self.dirty or self.form_dirty:
            self.status.setText('Save or reload your edits before re-enabling a source.')
            return
        if QMessageBox.question(self, 'Re-enable source?',
                f'{host} was paused because of an access challenge. Review the source access conditions. '
                'Resume requests to this host?') == QMessageBox.StandardButton.Yes:
            self._request('resume', host=host)

    def _retry(self):
        if not self.current_id:
            self.status.setText('Select a source first.')
            return
        if self.dirty or self.form_dirty:
            self.status.setText('Save or reload your edits before retrying.')
            return
        self._request('retry', source_id=self.current_id)

    def _handle_reply(self, session_id, channel=None, source=None, payload=None, **_):
        if session_id != self.session_id or not isinstance(payload, dict):
            return
        content = payload.get('content')
        if isinstance(content, dict) and content.get('token') == self.token and content.get('agent_uid') == self.agent_uid:
            self.received.emit(content)

    def _receive(self, content):
        if not self._signals_connected or not self.pending or content.get('request_id') != self.pending[0]:
            return
        operation = self.pending[1]; self.pending = None
        if not content.get('ok'):
            self._busy(False); self.status.setText('Request rejected: ' + str(content.get('error', 'unknown error')))
            return
        if (type(content.get('revision')) is not int or not isinstance(content.get('sources'), list)
                or not isinstance(content.get('blocked_hosts'), dict) or not isinstance(content.get('events'), list)):
            self._busy(False); self.status.setText('Invalid response; reload to confirm saved state.')
            return
        self.revision = content['revision']; self.sources = deepcopy(content['sources'])
        self.blocked = deepcopy(content['blocked_hosts']); self.events = deepcopy(content['events'])
        self.observations = deepcopy(content.get('observations', {}))
        self.analysis_errors = deepcopy(content.get('analysis_errors', {}))
        self.pending_counts = deepcopy(content.get('pending_counts', {}))
        self.dirty = False; self._clear(); self._render(); self._busy(False)
        self.status.setText(('Saved' if operation == 'update' else 'Loaded') +
            f' {len(self.sources)} sources; {len(self.blocked)} hosts paused. Reload to refresh activity.')

    def _tick(self):
        if self.pending and time.monotonic() - self.pending[2] > 20:
            self.pending = None; self._busy(False)
            self.status.setText('No acknowledgment; draft preserved. Reload to confirm saved state.')

    def _connect_signals(self):
        if not self._signals_connected:
            self.bus.on(self.REPLY_EVENT, self._handle_reply)
            self._signals_connected = True

    def _disconnect_signals(self):
        if self._signals_connected:
            self.bus.off(self.REPLY_EVENT, self._handle_reply)
            self._signals_connected = False

    def _on_show(self):
        self.timer.start()
        if self.revision is None and not self.pending:
            self._request('get')

    def _on_hide(self):
        self.timer.stop()
        if self.pending:
            self.pending = None; self._busy(False)
            self.status.setText('Request interrupted; reload to confirm agent state.')

    def get_panel_buttons(self):
        return [PanelButton(self.ICON, self.DISPLAY_NAME, lambda: self.session_window.show_specialty_panel(self))]
