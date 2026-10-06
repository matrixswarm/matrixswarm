"""Read-only Log Monitor with explicit, previewed Oracle requests."""
import json
import time
import uuid
from collections import deque

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface


def label(text):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


def clock_text(value):
    try:
        return time.strftime("%H:%M:%S", time.localtime(value)) if value else "not yet"
    except (ValueError, TypeError, OverflowError, OSError):
        return "unknown"


class LogHealth(PhoenixPanelInterface):
    cache_panel = True
    received = pyqtSignal(str, object)

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self.agent_uid = (node or {}).get("universal_id")
        self.token = uuid.uuid4().hex
        self.stream = None
        self.cursor = 0
        self.events = deque(maxlen=500)
        self.display_events = []
        self.pending = {}
        self._signals_connected = False
        self._last_reply = None
        self._next_poll = 0
        self._skipped = 0
        self._preview = None
        layout = QVBoxLayout(self)
        layout.addWidget(label("Log Monitor"))
        self.path_label = label("Waiting for the agent's configured log path.")
        layout.addWidget(self.path_label)
        self.status_label = label("Connecting…")
        layout.addWidget(self.status_label)
        self.access_label = label("Check access opens the configured file as the agent's Linux account; it changes no permissions.")
        layout.addWidget(self.access_label)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search recent events…")
        self.search.textChanged.connect(self._render)
        row.addWidget(self.search, 1)
        self.severity = QComboBox()
        self.severity.addItems(["All severities", "CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"])
        self.severity.currentTextChanged.connect(self._render)
        row.addWidget(self.severity)
        self.pause = QPushButton("Pause display")
        self.pause.setCheckable(True)
        self.pause.toggled.connect(self._pause_changed)
        row.addWidget(self.pause)
        self.access = QPushButton("Check access")
        self.access.clicked.connect(lambda: self._request("snapshot", check_access=True))
        row.addWidget(self.access)
        self.ask = QPushButton("Ask Oracle…")
        self.ask.clicked.connect(self._ask_oracle)
        row.addWidget(self.ask)
        layout.addLayout(row)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Received", "Severity", "Log entry"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.count_label = label("New entries after agent startup appear here. Recent events are held in memory.")
        layout.addWidget(self.count_label)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(90)
        self.detail.setPlaceholderText("Select an event to read its full captured text. Ctrl/Shift selects several for Oracle.")
        self.table.itemSelectionChanged.connect(self._show_selection)
        layout.addWidget(self.detail)
        self.analysis = QPlainTextEdit()
        self.analysis.setReadOnly(True)
        self.analysis.setMaximumHeight(180)
        self.analysis.setPlaceholderText("Oracle analysis appears here. Ask Oracle previews selected entries, or the latest visible entries.")
        layout.addWidget(self.analysis)
        self.received.connect(self._receive)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._tick)
        self._timers.append(self.timer)

    def _request(self, kind, **extra):
        if not self._signals_connected or kind in self.pending:
            return
        request_id = uuid.uuid4().hex
        self.pending[kind] = (request_id, time.monotonic())
        if kind == "snapshot":
            extra.update(cursor=self.cursor, stream=self.stream)
            self.access.setEnabled(False)
        else:
            self.ask.setEnabled(False)
            self.analysis.setPlainText("Oracle is analyzing the reviewed excerpt…")
        packet = Packet()
        packet.set_data({"handler": "cmd_service_request", "ts": time.time(), "content": {
            "service": "hive.log_health." + ("analyze" if kind == "analysis" else "snapshot"),
            "payload": dict(extra, target_universal_id=self.agent_uid,
                            session_id=self.session_id, token=self.token, request_id=request_id)}})
        try:
            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=packet)
        except Exception:
            self.pending.pop(kind, None)
            self._failure(kind, "Request could not be sent.")

    def _failure(self, kind, message):
        if kind == "snapshot":
            self.access.setEnabled(True)
            self.status_label.setText(message + " Displayed entries may be old.")
        else:
            self.ask.setEnabled(True)
            self.analysis.setPlainText(message)

    def _snapshot_callback(self, session_id, payload=None, **_):
        self._callback("snapshot", session_id, payload)

    def _analysis_callback(self, session_id, payload=None, **_):
        self._callback("analysis", session_id, payload)

    def _callback(self, kind, session_id, payload):
        if (session_id != self.session_id or not isinstance(payload, dict)
                or payload.get("verified_sender") != self.agent_uid):
            return
        content = payload.get("content")
        if (not isinstance(content, dict) or content.get("agent_uid") != self.agent_uid
                or content.get("token") != self.token):
            return
        self.received.emit(kind, content)

    def _receive(self, kind, content):
        pending = self.pending.get(kind)
        if (not self._signals_connected or not pending
                or content.get("token") != self.token
                or content.get("request_id") != pending[0]):
            return
        self.pending.pop(kind, None)
        if not content.get("ok"):
            self._failure(kind, str(content.get("error", "Agent rejected the request."))[:1000])
            return
        if kind == "analysis":
            self.ask.setEnabled(True)
            self.analysis.setPlainText("Oracle analysis — suggestions only; no actions were run.\n\n"
                                       + str(content.get("response", "No analysis returned."))[:12000])
            return
        self.access.setEnabled(True)
        events, cursor, stream = content.get("events"), content.get("cursor"), content.get("stream")
        skipped = content.get("skipped", 0)
        if (not isinstance(events, list) or len(events) > 100 or type(cursor) is not int
                or not isinstance(stream, str) or not stream or len(stream) > 128 or cursor < 0
                or type(skipped) is not int or skipped < 0
                or any(not isinstance(event, dict) or type(event.get("id")) is not int
                       or event["id"] < 1 or event["id"] > cursor
                       or not isinstance(event.get("text"), str) or len(event["text"]) > 2048
                       for event in events)):
            self._failure(kind, "Invalid agent response.")
            return
        if stream != self.stream or content.get("reset"):
            self.events.clear()
            self._skipped = 0
            self.cursor = 0
        for event in events:
            if event["id"] > self.cursor:
                self.events.append(event)
        self.stream, self.cursor = stream, cursor
        self._skipped += skipped
        self._last_reply = time.monotonic()
        self._next_poll = self._last_reply + (0.5 if content.get("more") else 2)
        self.path_label.setText(str(content.get("service_name", "")) + " · " + str(content.get("log_path", "")))
        self.status_label.setText(
            str(content.get("state", "unknown")).capitalize()
            + " · Last successful read: " + clock_text(content.get("last_read"))
            + " · Last event: " + clock_text(content.get("last_event"))
            + " · Rotations/truncations: " + str(content.get("rotations", 0)))
        access = content.get("access")
        if isinstance(access, dict):
            self.access_label.setText("Access check: " + str(access.get("result", "unknown"))
                                      + " at " + clock_text(access.get("checked_at"))
                                      + " · No permissions changed.")
        if not self.pause.isChecked():
            self.display_events = list(self.events)
            self._render()

    def _visible_events(self):
        search = self.search.text().casefold()
        severity = self.severity.currentText()
        return [event for event in self.display_events
                if (severity == "All severities" or event.get("severity") == severity)
                and search in event["text"].casefold()]

    def _selected_ids(self):
        return {self.table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
                for index in self.table.selectionModel().selectedRows()}

    def _render(self, *_):
        selected = self._selected_ids()
        scroll = self.table.verticalScrollBar()
        at_bottom, position = scroll.value() >= scroll.maximum(), scroll.value()
        visible = self._visible_events()
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setRowCount(len(visible))
        for row, event in enumerate(visible):
            values = [clock_text(event.get("time")), str(event.get("severity", "INFO")),
                      event["text"] + (" [line shortened]" if event.get("truncated") else "")]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, event["id"])
                self.table.setItem(row, column, item)
                if event["id"] in selected:
                    item.setSelected(True)
        self.table.blockSignals(False)
        if at_bottom and not selected:
            self.table.scrollToBottom()
        else:
            scroll.setValue(position)
        self.count_label.setText(
            f"{len(visible)} visible / {len(self.display_events)} buffered (maximum 500)"
            + (f" · {self._skipped} earlier events outside the fetched window" if self._skipped else "")
            + (" · Display paused; agent keeps reading" if self.pause.isChecked() else ""))
        self._show_selection()

    def _show_selection(self):
        selected = self._selected_ids()
        self.detail.setPlainText("\n".join(event["text"] for event in self.display_events
                                          if event["id"] in selected)[:12000])

    def _pause_changed(self, paused):
        self.pause.setText("Resume display" if paused else "Pause display")
        if not paused:
            self.display_events = list(self.events)
        self._render()

    def _ask_oracle(self):
        selected = self._selected_ids()
        candidates = [event for event in self._visible_events() if not selected or event["id"] in selected]
        if not candidates:
            self.analysis.setPlainText("No visible events to analyze yet. Wait for new log entries or change the filters.")
            return
        lines, used = [], 0
        for event in reversed(candidates[-20:]):
            line = f"{clock_text(event.get('time'))} [{event.get('severity', 'INFO')}] {event['text']}"
            cost = len(json.dumps(line, ensure_ascii=True).encode("ascii")) + 2
            if used + cost > 6000:
                break
            lines.append(line)
            used += cost
        dialog = QDialog(self)
        self._preview = dialog
        dialog.setWindowTitle("Ask Oracle — review log excerpt")
        dialog.resize(760, 480)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label(
            "This excerpt will be sent to Oracle's configured AI provider (OpenAI). "
            "Remove passwords, tokens or personal data before sending. Oracle's prompt-dump "
            "setting, if enabled, may also record it in Oracle's logs. Nothing is executed."))
        editor = QPlainTextEdit()
        editor.setPlainText("\n".join(reversed(lines)))
        layout.addWidget(editor, 1)
        count = label("")
        layout.addWidget(count)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Send to Oracle")
        layout.addWidget(buttons)
        def update_count():
            text = editor.toPlainText()
            size = len(json.dumps(text, ensure_ascii=True).encode("ascii"))
            count.setText(f"{size} / 7000 encoded bytes · Review and edit the excerpt above.")
            buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(text.strip()) and size <= 7000
                                                                        and len(text.encode('utf-8')) <= 6000)
        editor.textChanged.connect(update_count)
        update_count()
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        self._preview = None
        if accepted and self._signals_connected:
            self._request("analysis", excerpt=editor.toPlainText())
        dialog.deleteLater()

    def _tick(self):
        now = time.monotonic()
        for kind, (_, started) in list(self.pending.items()):
            if now - started > (100 if kind == "analysis" else 15):
                self.pending.pop(kind, None)
                message = ("No signed reply. Check connection and deploy Log Health with its monitor routes and packet signing."
                           if kind == "snapshot" else "Oracle did not reply. Check its configuration and logs.")
                self._failure(kind, message)
        if now >= self._next_poll:
            self._next_poll = now + 2
            self._request("snapshot")
        if self._last_reply is not None and now - self._last_reply > 20:
            self.status_label.setText("Connection stale — displayed entries may be old.")

    def _connect_signals(self):
        if not self._signals_connected:
            self.bus.on("inbound.verified.log_health.snapshot", self._snapshot_callback)
            self.bus.on("inbound.verified.log_health.analysis", self._analysis_callback)
            self._signals_connected = True

    def _disconnect_signals(self):
        if self._signals_connected:
            self.bus.off("inbound.verified.log_health.snapshot", self._snapshot_callback)
            self.bus.off("inbound.verified.log_health.analysis", self._analysis_callback)
            self._signals_connected = False

    def _on_show(self):
        self.timer.start()
        self._request("snapshot")

    def _on_hide(self):
        self.timer.stop()
        if self._preview is not None:
            self._preview.reject()
        if "analysis" in self.pending:
            self.analysis.setPlainText("Panel closed while waiting for Oracle. The submitted request may still finish remotely.")
        self.pending.clear()
        self.token = uuid.uuid4().hex
        self.access.setEnabled(True)
        self.ask.setEnabled(True)

    def _on_close(self):
        self._on_hide()

    def get_panel_buttons(self):
        return [PanelButton("≡", "Log Monitor", lambda: self.session_window.show_specialty_panel(self))]
