"""Phoenix editor for encrypted Global Alarm schedules."""
import time
import uuid
from copy import deepcopy
from datetime import datetime, timedelta

from PyQt6.QtCore import QDateTime, QTimeZone, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateTimeEdit,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget)

from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton


class GlobalAlarm(PhoenixPanelInterface):
    cache_panel = True
    received = pyqtSignal(object)
    clock_received = pyqtSignal(object)

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self.agent_uid = (node or {}).get("universal_id")
        self.token = uuid.uuid4().hex
        self.alarms = []
        self._saved_by_id = {}
        self.destinations = []
        self.default_alert_role = "hive.alert"
        self.legacy_destinations = []
        self.runtime = {}
        self.revision = None
        self.pending = None
        self.dirty = False
        self.form_dirty = False
        self.current_id = None
        self._populating = False
        self._signals_connected = False
        self._clock_pending = None
        self._clock_sample = None
        self._next_clock_refresh = 0
        self.setLayout(self._build_ui())
        self.received.connect(self._receive)
        self.clock_received.connect(self._receive_clock)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self._timers.append(self.timer)
        self._busy(False)

    def _build_ui(self):
        layout = QVBoxLayout()
        title = QLabel("⏰ Global Alarm")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)
        help_text = QLabel("Create reminders and choose the service role that receives each alert. "
            "Save Changes activates edits. Times use the selected IANA time zone; "
            "delivery continues while Phoenix is closed.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.status = QLabel("Open this panel to load saved alarms.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.clock_label = QLabel("Server time: waiting for the agent…")
        self.clock_label.setTextFormat(Qt.TextFormat.PlainText)
        self.clock_label.setWordWrap(True)
        layout.addWidget(self.clock_label)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Title", "Local time", "Repeat", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 210)
        self.table.setColumnWidth(2, 70)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._selected)
        split.addWidget(self.table)
        self.editor = QWidget()
        form = QFormLayout(self.editor)
        self.title_edit = QLineEdit()
        self.title_edit.setMaxLength(120)
        self.message_edit = QTextEdit()
        self.message_edit.setMaximumHeight(120)
        self.when_edit = QDateTimeEdit()
        self.when_edit.setCalendarPopup(True)
        self.when_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.timezone_edit = QLineEdit("UTC")
        self.timezone_edit.setPlaceholderText("e.g. America/New_York")
        self.repeat = QComboBox()
        self.repeat.addItem("Once", "once")
        self.repeat.addItem("Daily", "daily")
        self.repeat.addItem("Weekly", "weekly")
        self.enabled = QCheckBox("Enabled")
        self.enabled.setChecked(True)
        self.alert_role = QLineEdit()
        self.alert_role.setPlaceholderText("hive.alert")
        self.alert_role.setToolTip("Alerts go to agents advertising this service-manager role.")
        self.use_role = QCheckBox("Change this older alarm to service-role routing")
        self.legacy_note = QLabel()
        self.legacy_note.setTextFormat(Qt.TextFormat.PlainText)
        self.legacy_note.setWordWrap(True)
        form.addRow("Title", self.title_edit)
        form.addRow("Message", self.message_edit)
        form.addRow("Date and time", self.when_edit)
        form.addRow("Time zone", self.timezone_edit)
        form.addRow("Repeat", self.repeat)
        form.addRow("", self.enabled)
        form.addRow("Alert to role", self.alert_role)
        form.addRow(self.legacy_note)
        form.addRow(self.use_role)
        self.use_role.toggled.connect(self._set_routing_mode)
        self.btn_apply = QPushButton("Add / Update Draft")
        self.btn_apply.clicked.connect(self._apply)
        form.addRow(self.btn_apply)
        split.addWidget(self.editor)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        layout.addWidget(split, 1)
        row = QHBoxLayout()
        self.btn_new = QPushButton("New")
        self.btn_delete = QPushButton("Delete")
        self.btn_reload = QPushButton("Reload Saved")
        self.btn_save = QPushButton("Save Changes")
        self.btn_new.clicked.connect(self._new)
        self.btn_delete.clicked.connect(self._delete)
        self.btn_reload.clicked.connect(self._reload)
        self.btn_save.clicked.connect(self._save)
        for button in (self.btn_new, self.btn_delete, self.btn_reload, self.btn_save):
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        for signal in (self.title_edit.textChanged, self.message_edit.textChanged,
                       self.when_edit.dateTimeChanged, self.timezone_edit.textChanged,
                       self.repeat.currentIndexChanged, self.enabled.stateChanged,
                       self.alert_role.textChanged, self.use_role.stateChanged):
            signal.connect(self._form_changed)
        self._clear_form()
        return layout

    def _busy(self, busy):
        ready = self.revision is not None and not busy
        self.table.setEnabled(ready)
        self.editor.setEnabled(ready)
        self.btn_new.setEnabled(ready)
        self.btn_delete.setEnabled(ready)
        self.btn_save.setEnabled(ready)
        self.btn_reload.setEnabled(not busy)

    def _form_changed(self, *_):
        if not self._populating:
            self.form_dirty = True
            self.status.setText("Unsaved form edit — click Save Changes to activate it.")
            for row, alarm in enumerate(self.alarms):
                if alarm["id"] == self.current_id and self.table.item(row, 3):
                    self.table.item(row, 3).setText("Unsaved edit")
                    break

    def _set_routing_mode(self, checked):
        self.alert_role.setEnabled(not self.legacy_destinations or checked)

    def _clear_form(self):
        self._populating = True
        self.current_id = None
        self.title_edit.clear()
        self.message_edit.clear()
        local_zone = bytes(QTimeZone.systemTimeZoneId()).decode("utf-8", errors="replace") or "UTC"
        self.when_edit.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        self.timezone_edit.setText(local_zone)
        self.repeat.setCurrentIndex(0)
        self.enabled.setChecked(True)
        self.legacy_destinations = []
        self.alert_role.setText(self.default_alert_role)
        self.use_role.setChecked(True)
        self.use_role.hide()
        self.legacy_note.hide()
        self._set_routing_mode(True)
        self.form_dirty = False
        self._populating = False

    def _discard_form(self):
        if not self.form_dirty:
            return True
        return QMessageBox.question(self, "Discard form edits?",
            "The current form has not been added or updated. Discard those edits?") == QMessageBox.StandardButton.Yes

    def _new(self):
        if not self._discard_form():
            return
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.blockSignals(False)
        self._clear_form()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        if row >= len(self.alarms):
            return
        alarm = self.alarms[row]
        if alarm["id"] == self.current_id:
            return
        if not self._discard_form():
            self.table.blockSignals(True)
            self.table.clearSelection()
            for i, old in enumerate(self.alarms):
                if old["id"] == self.current_id:
                    self.table.selectRow(i)
                    break
            self.table.blockSignals(False)
            return
        self._populating = True
        self.current_id = alarm["id"]
        self.title_edit.setText(alarm["title"])
        self.message_edit.setPlainText(alarm["message"])
        self.when_edit.setDateTime(QDateTime.fromString(alarm["start_local"], "yyyy-MM-ddTHH:mm"))
        self.timezone_edit.setText(alarm["timezone"])
        self.repeat.setCurrentIndex(max(0, self.repeat.findData(alarm["repeat"])))
        self.enabled.setChecked(alarm["enabled"])
        self.legacy_destinations = list(alarm.get("destinations", []))
        legacy = bool(self.legacy_destinations) and "alert_role" not in alarm
        self.alert_role.setText(alarm.get("alert_role", self.default_alert_role))
        self.use_role.setVisible(legacy)
        self.use_role.setChecked(not legacy)
        self.legacy_note.setVisible(legacy)
        self.legacy_note.setText("Existing relay targets: " + ", ".join(self.legacy_destinations))
        self._set_routing_mode(not legacy)
        self.form_dirty = False
        self._populating = False

    def _apply(self):
        title = self.title_edit.text().strip()
        message = self.message_edit.toPlainText().strip()
        use_role = not self.legacy_destinations or self.use_role.isChecked()
        role = self.alert_role.text().strip()
        if (not title or not message or len(message) > 2000 or not self.timezone_edit.text().strip()
                or (use_role and (not role or len(role) > 128 or "@" in role))):
            self.status.setText("Enter a title, message, time zone, and alert service role without a handler.")
            return False
        alarm = {"id": self.current_id or uuid.uuid4().hex, "title": title, "message": message,
                 "start_local": self.when_edit.dateTime().toString("yyyy-MM-ddTHH:mm"),
                 "timezone": self.timezone_edit.text().strip(), "repeat": self.repeat.currentData(),
                 "enabled": self.enabled.isChecked()}
        if use_role:
            alarm["alert_role"] = role
        else:
            alarm["destinations"] = list(self.legacy_destinations)
        index = next((i for i, a in enumerate(self.alarms) if a["id"] == alarm["id"]), None)
        if index is None:
            self.alarms.append(alarm)
            index = len(self.alarms) - 1
        else:
            self.alarms[index] = alarm
        self.current_id = alarm["id"]
        self.form_dirty = False
        self.dirty = True
        self._render_table(index)
        self.status.setText("Alarm added to draft — Save Changes to activate it.")
        return True

    def _delete(self):
        if not self.current_id or not self._discard_form():
            return
        self.alarms = [a for a in self.alarms if a["id"] != self.current_id]
        self._clear_form()
        self.dirty = True
        self._render_table()
        self.status.setText("Alarm removed from draft — Save Changes to apply.")

    def _render_table(self, select=None):
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.setRowCount(len(self.alarms))
        for row, alarm in enumerate(self.alarms):
            state = self.runtime.get(alarm["id"], {})
            pending = state.get("pending") or {}
            targets = pending.get("destinations") or []
            if alarm != self._saved_by_id.get(alarm["id"]):
                status = "Unsaved"
            elif self.form_dirty and self.current_id == alarm["id"]:
                status = "Unsaved edit"
            elif not alarm["enabled"]:
                status = "Disabled"
            elif pending and not targets:
                status = "Waiting for matching role"
            elif pending:
                status = f"Queueing {len(pending.get('queued', []))}/{len(targets)}"
            elif alarm["repeat"] == "once" and state.get("last_queued"):
                status = "Queued"
            else:
                status = "Scheduled"
            for column, value in enumerate((alarm["title"], alarm["start_local"] + " " + alarm["timezone"],
                                            alarm["repeat"].title(), status)):
                self.table.setItem(row, column, QTableWidgetItem(value))
        if select is not None:
            self.table.selectRow(select)
        self.table.blockSignals(False)

    def _request(self, operation, **extra):
        if self.pending:
            return
        request_id = uuid.uuid4().hex
        self.pending = (request_id, operation, time.monotonic())
        self._busy(True)
        payload = dict(extra, target_universal_id=self.agent_uid, session_id=self.session_id,
                       token=self.token, request_id=request_id)
        packet = Packet()
        packet.set_data({"handler": "cmd_service_request", "ts": time.time(),
                         "content": {"service": "hive.global_alarm." + operation, "payload": payload}})
        self.status.setText("Saving alarms…" if operation == "update" else "Loading alarms…")
        try:
            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=packet)
        except Exception:
            self.pending = None
            self._busy(False)
            self.status.setText("Request could not be sent. Your draft is preserved.")

    def _save(self):
        if self.form_dirty and not self._apply():
            return
        self._request("update", revision=self.revision, alarms=deepcopy(self.alarms))

    def _reload(self):
        if (self.dirty or self.form_dirty) and QMessageBox.question(self, "Reload Saved",
                "Discard unsaved alarm edits and reload from the agent?") != QMessageBox.StandardButton.Yes:
            return
        self._request("get")

    def _handle_reply(self, session_id, channel=None, source=None, payload=None, **_):
        if session_id != self.session_id or not isinstance(payload, dict):
            return
        content = payload.get("content")
        if (isinstance(content, dict) and content.get("token") == self.token
                and content.get("agent_uid") == self.agent_uid):
            self.received.emit(content)

    def _receive(self, content):
        if not self._signals_connected or not self.pending or content.get("request_id") != self.pending[0]:
            return
        operation = self.pending[1]
        self.pending = None
        if not content.get("ok"):
            self._busy(False)
            self.status.setText("Request rejected: " + str(content.get("error", "unknown error")))
            return
        if (type(content.get("revision")) is not int or not isinstance(content.get("alarms"), list)
                or not isinstance(content.get("destinations"), list) or not isinstance(content.get("runtime"), dict)):
            self._busy(False)
            self.status.setText("Invalid response. Reload Saved to confirm the agent state.")
            return
        self.revision = content["revision"]
        self.alarms = deepcopy(content["alarms"])
        self._saved_by_id = {alarm["id"]: deepcopy(alarm) for alarm in self.alarms}
        self.destinations = list(content["destinations"])
        self.default_alert_role = content.get("default_alert_role") or "hive.alert"
        self.runtime = deepcopy(content["runtime"])
        self._set_clock_sample(content.get("server_clock"))
        self.dirty = False
        self._clear_form()
        self._render_table()
        self._busy(False)
        self.status.setText(("Saved" if operation == "update" else "Loaded") +
            f" {len(self.alarms)} alarms. Default role: {self.default_alert_role}. "
            "Relay queueing does not confirm final delivery.")

    def _tick(self):
        now = time.monotonic()
        if self.pending and time.monotonic() - self.pending[2] > 20:
            self.pending = None
            self._busy(False)
            self.status.setText("No acknowledgment. Draft preserved; reload to confirm what was saved.")
        if self._clock_pending and now - self._clock_pending[1] > 20:
            self._clock_pending = None
        if self._signals_connected and not self._clock_pending and now >= self._next_clock_refresh:
            self._request_clock()
        self._render_clock(now)

    def _request_clock(self):
        request_id = uuid.uuid4().hex
        now = time.monotonic()
        self._clock_pending = (request_id, now)
        self._next_clock_refresh = now + 15
        packet = Packet()
        packet.set_data({"handler": "cmd_service_request", "ts": time.time(), "content": {
            "service": "hive.global_alarm.get", "payload": {
                "target_universal_id": self.agent_uid, "session_id": self.session_id,
                "token": self.token, "request_id": request_id, "clock_only": True}}})
        try:
            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=packet)
        except Exception:
            self._clock_pending = None

    def _handle_clock(self, session_id, channel=None, source=None, payload=None, **_):
        if session_id != self.session_id or not isinstance(payload, dict):
            return
        content = payload.get("content")
        if (isinstance(content, dict) and content.get("token") == self.token
                and content.get("agent_uid") == self.agent_uid):
            self.clock_received.emit(content)

    def _set_clock_sample(self, sample):
        if not isinstance(sample, dict):
            return
        try:
            value = datetime.fromisoformat(sample["local_time"])
            if value.utcoffset() is None:
                return
        except (KeyError, TypeError, ValueError, OverflowError):
            return
        zone = sample.get("timezone") or sample.get("abbreviation") or "unknown zone"
        if not isinstance(zone, str) or len(zone) > 128:
            zone = "unknown zone"
        self._clock_sample = (value, zone, time.monotonic())
        self._render_clock(time.monotonic())

    def _render_clock(self, now):
        if self._clock_sample is None:
            self.clock_label.setText("Server time: waiting for the agent (older agents may not report it).")
            return
        value, zone, sampled = self._clock_sample
        age = max(0, int(now - sampled))
        if age > 45:
            self.clock_label.setText(f"Server time: last reported {value:%Y-%m-%d %H:%M:%S %z} "
                                     f"({zone}); stale, {age}s since update.")
            return
        estimated = value + timedelta(seconds=age)
        self.clock_label.setText(f"Server time (estimated): {estimated:%Y-%m-%d %H:%M:%S %z} "
                                 f"({zone}) · synced {age}s ago")

    def _receive_clock(self, content):
        if (not self._signals_connected or not self._clock_pending
                or content.get("request_id") != self._clock_pending[0]):
            return
        self._clock_pending = None
        if not content.get("ok"):
            return
        self._set_clock_sample(content.get("server_clock"))
        runtime = content.get("runtime")
        if content.get("revision") == self.revision and isinstance(runtime, dict):
            self.runtime = deepcopy(runtime)
            selected = next((i for i, alarm in enumerate(self.alarms)
                             if alarm["id"] == self.current_id), None)
            self._render_table(selected)

    def _connect_signals(self):
        if not self._signals_connected:
            self.bus.on("inbound.verified.global_alarm.config", self._handle_reply)
            self.bus.on("inbound.verified.global_alarm.clock", self._handle_clock)
            self._signals_connected = True

    def _disconnect_signals(self):
        if self._signals_connected:
            self.bus.off("inbound.verified.global_alarm.config", self._handle_reply)
            self.bus.off("inbound.verified.global_alarm.clock", self._handle_clock)
            self._signals_connected = False

    def _on_show(self):
        self.timer.start()
        self._next_clock_refresh = 0
        if self.revision is None and not self.pending:
            self._request("get")

    def _on_hide(self):
        self.timer.stop()
        self._clock_pending = None
        if self.pending:
            self.pending = None
            self._busy(False)
            self.status.setText("Request interrupted; reload to confirm agent state.")

    def get_panel_buttons(self):
        return [PanelButton("⏰", "Global Alarm", lambda: self.session_window.show_specialty_panel(self))]
