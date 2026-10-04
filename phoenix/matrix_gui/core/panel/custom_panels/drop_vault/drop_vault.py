"""A traveling clipboard backed by a dedicated encrypted MatrixOS agent."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import re
import time
import uuid

from PyQt6.QtCore import QEvent, QMimeData, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QTextDocumentFragment
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHeaderView, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTabWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton
from .local_files import FileJob, MAX_BYTES

CHUNK = 8 * 1024


def _plain_drop_text(source):
    """Use plain text from a browser drag; never treat a local file as paste."""
    if source.hasUrls() and any(url.isLocalFile() for url in source.urls()):
        return None
    if source.hasText():
        return source.text()
    if source.hasHtml():
        html = source.html()
        if len(html.encode("utf-8")) > 4 * MAX_BYTES:
            return None
        return QTextDocumentFragment.fromHtml(html).toPlainText()
    return None


class PasteEditor(QPlainTextEdit):
    """Accept browser text as plain draft text, never a dragged local file."""

    draft_inserted = pyqtSignal()
    draft_rejected = pyqtSignal()

    def canInsertFromMimeData(self, source):
        return _plain_drop_text(source) is not None

    def insertFromMimeData(self, source):
        text = _plain_drop_text(source)
        if text is None:
            return
        self.insert_draft_text(text)

    def insert_draft_text(self, text):
        selected = self.textCursor().selectedText().replace("\u2029", "\n")
        size = len(self.toPlainText().encode("utf-8")) - len(selected.encode("utf-8"))
        if size + len(text.encode("utf-8")) > MAX_BYTES:
            self.draft_rejected.emit()
            return False
        self.insertPlainText(text)
        self.draft_inserted.emit()
        return True


class PasteTab(QWidget):
    """Drop surface includes the tab header, buttons and editor viewport."""

    drop_rejected = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.editor = None
        self.hint = None
        self._hovering = False
        self.setAcceptDrops(True)

    def watch(self, widget):
        widget.setAcceptDrops(True)
        widget.installEventFilter(self)

    def _highlight(self, active):
        if self._hovering == active:
            return
        self._hovering = active
        if self.hint is not None:
            color = "#00c9ae" if active else "#647d8a"
            self.hint.setStyleSheet(f"QLabel {{ border: 1px dashed {color}; padding: 6px; }}")

    def _drag_event(self, target, event):
        kind = event.type()
        if kind == QEvent.Type.DragLeave:
            self._highlight(False)
            event.accept()
            return True
        text = _plain_drop_text(event.mimeData())
        if text is None:
            self._highlight(False)
            if kind == QEvent.Type.DragEnter:
                local_file = (event.mimeData().hasUrls()
                              and any(url.isLocalFile() for url in event.mimeData().urls()))
                self.drop_rejected.emit(
                    "Local files belong in the Drop files tab."
                    if local_file else "This drag contains no plain or HTML text; use Copy then Paste instead.")
            event.ignore()
            return True
        if kind in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            self._highlight(True)
            event.acceptProposedAction()
            return True
        if kind == QEvent.Type.Drop:
            self._highlight(False)
            if target is self.editor.viewport():
                self.editor.setTextCursor(self.editor.cursorForPosition(event.position().toPoint()))
            if self.editor.insert_draft_text(text):
                self.editor.setFocus()
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
            else:
                event.ignore()
            return True
        return False

    def dragEnterEvent(self, event):
        self._drag_event(self, event)

    def dragMoveEvent(self, event):
        self._drag_event(self, event)

    def dragLeaveEvent(self, event):
        self._drag_event(self, event)

    def dropEvent(self, event):
        self._drag_event(self, event)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove,
                            QEvent.Type.DragLeave, QEvent.Type.Drop):
            return self._drag_event(watched, event)
        return super().eventFilter(watched, event)


class DropArea(QLabel):
    files = pyqtSignal(object)
    text_dropped = pyqtSignal(str)
    PROMPT = "Drop files here to upload\n(or drop text to prepare a paste)"
    COLORS = {"idle": "#647d8a", "hover": "#00c9ae", "busy": "#d5a83e",
              "saved": "#28c787", "notice": "#65b8de", "error": "#e07171"}
    BACKGROUNDS = {"idle": "#101114", "hover": "#10231e", "busy": "#292313",
                   "saved": "#10251b", "notice": "#11212a", "error": "#281619"}

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setMinimumHeight(100)
        self._state = "idle"
        self._message = self.PROMPT
        self._render()

    def _render(self, hover=False):
        state = "hover" if hover else self._state
        color = self.COLORS[state]
        background = self.BACKGROUNDS[state]
        self.setStyleSheet(f"QLabel {{ border: 2px dashed {color}; border-radius: 7px; "
                           f"background-color: {background}; color: {color}; "
                           "font-weight: 600; padding: 18px; }")
        self.setText(self._message)

    def set_feedback(self, state="idle", message=None):
        self._state = state
        self._message = message or self.PROMPT
        self._render()

    @staticmethod
    def _accepts(mime):
        if mime.hasUrls():
            urls = mime.urls()
            return 0 < len(urls) <= 16 and all(url.isLocalFile() for url in urls)
        return mime.hasText()

    def dragEnterEvent(self, event):
        if self._accepts(event.mimeData()):
            self._render(hover=True)
            self.setText("Local file recognized · release to upload."
                         if event.mimeData().hasUrls() else "Text recognized · release to prepare a paste.")
            event.acceptProposedAction()
        else:
            self.set_feedback("error", "Phoenix received this drag, but it is not a local file or plain text.")
            event.ignore()

    def dragMoveEvent(self, event):
        if self._accepts(event.mimeData()):
            self._render(hover=True)
            self.setText("Local file recognized · release to upload."
                         if event.mimeData().hasUrls() else "Text recognized · release to prepare a paste.")
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._render()
        event.accept()

    def dropEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls():
            urls = mime.urls()
            if not (0 < len(urls) <= 16 and all(url.isLocalFile() for url in urls)):
                return
            self.set_feedback("busy", f"Drop received · preparing {len(urls)} file(s)…\nPlease wait; do not drop again.")
            self.files.emit([url.toLocalFile() for url in urls])
        elif mime.hasText():
            self.set_feedback("notice", "Text prepared in Paste tab · press Upload Text to send it.")
            self.text_dropped.emit(mime.text())
        else:
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()


class DropFilesTab(QWidget):
    """Forward drags from the whole tab, including its button, to DropArea."""

    def __init__(self):
        super().__init__()
        self.area = None
        self.setAcceptDrops(True)

    def watch(self, widget):
        widget.setAcceptDrops(True)
        widget.installEventFilter(self)

    def _route(self, event):
        if self.area is None or not self.area.isEnabled():
            event.ignore()
            return True
        handlers = {QEvent.Type.DragEnter: self.area.dragEnterEvent,
                    QEvent.Type.DragMove: self.area.dragMoveEvent,
                    QEvent.Type.DragLeave: self.area.dragLeaveEvent,
                    QEvent.Type.Drop: self.area.dropEvent}
        handlers[event.type()](event)
        return True

    def dragEnterEvent(self, event):
        self._route(event)

    def dragMoveEvent(self, event):
        self._route(event)

    def dragLeaveEvent(self, event):
        self._route(event)

    def dropEvent(self, event):
        self._route(event)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove,
                            QEvent.Type.DragLeave, QEvent.Type.Drop):
            return self._route(event)
        return super().eventFilter(watched, event)


class DropVault(PhoenixPanelInterface):
    cache_panel = True
    received = pyqtSignal(object)

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self.agent_uid = (node or {}).get("universal_id")
        self.token = uuid.uuid4().hex
        self.pending = None
        self.transfer = None
        self.entries = {}
        self.loaded = None
        self.exported = None
        self.next_before = None
        self.page_before = None
        self._signals_connected = False
        self._job = None
        self._local_generation = 0
        self._queue = []
        self._recent_file_uploads = {}
        self._last_poll = 0
        self._clipboard_marker = None
        self.setLayout(self._build_ui())
        self.received.connect(self._receive)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self._timers.append(self.timer)
        self._buttons()

    def _build_ui(self):
        layout = QVBoxLayout()
        notice = QLabel("Drop Vault · Traveling clipboard\nEncrypted on the agent. Copy and Save create ordinary local copies; nothing is opened or executed automatically.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.status = QLabel("Open to retrieve the agent's saved listing.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        split = QSplitter()
        left, right = QWidget(), QWidget()
        composer, browser = QVBoxLayout(left), QVBoxLayout(right)
        self.title = QLineEdit()
        self.title.setPlaceholderText("Title (optional)")
        self.title.setMaxLength(256)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Notes (optional, up to 4096 UTF-8 bytes)")
        self.notes.setMaximumHeight(80)
        composer.addWidget(self.title)
        composer.addWidget(self.notes)
        self.tabs = QTabWidget()
        paste, drop = PasteTab(), DropFilesTab()
        paste.drop_rejected.connect(self.status.setText)
        paste_layout, drop_layout = QVBoxLayout(paste), QVBoxLayout(drop)
        self.paste = PasteEditor()
        self.paste.setPlaceholderText("Paste or drag selected browser text here; Upload Text sends it to the agent.")
        self.paste.setAcceptDrops(True)
        self.paste.textChanged.connect(self._paste_draft_changed)
        self.paste.draft_inserted.connect(
            lambda: self.status.setText("Text added to draft; this text has not been sent. Press Upload Text when ready."))
        self.paste.draft_rejected.connect(
            lambda: self.status.setText("Text would exceed the 1 MiB draft limit; nothing was added or sent."))
        paste.editor = self.paste
        self.paste_clipboard = QPushButton("Paste from clipboard")
        self.paste_clipboard.clicked.connect(lambda: self._draft_text(QApplication.clipboard().text()))
        paste.hint = QLabel("Drop selected text into the editor · Upload Text sends it")
        paste.hint.setTextFormat(Qt.TextFormat.PlainText)
        paste.hint.setStyleSheet("QLabel { border: 1px dashed #647d8a; padding: 6px; }")
        paste_layout.addWidget(paste.hint)
        paste_layout.addWidget(self.paste)
        self.paste_feedback = QLabel("Draft stays local until you press Upload Text.")
        self.paste_feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.paste_feedback.setWordWrap(True)
        paste_layout.addWidget(self.paste_feedback)
        self.send_text = QPushButton("Upload Text")
        self.send_text.clicked.connect(self._upload_text)
        paste_layout.addWidget(self.send_text)
        for widget in (paste.hint, self.paste_clipboard, self.paste, self.paste.viewport(), self.send_text):
            paste.watch(widget)
        self.drop = DropArea()
        drop.area = self.drop
        self.drop.files.connect(self._queue_files)
        self.drop.text_dropped.connect(self._draft_text)
        self.choose_files = QPushButton("Choose files…")
        self.choose_files.clicked.connect(self._choose_files)
        drop_layout.addWidget(self.drop)
        drop_layout.addWidget(self.choose_files)
        drop_note = QLabel("Small files and pasted text: up to 1 MiB per item.\n256 MiB / 1000 items per inbox.")
        drop_layout.addWidget(drop_note)
        drop_layout.addStretch()
        for widget in (self.drop, self.choose_files, drop_note):
            drop.watch(widget)
        self.tabs.addTab(paste, "Paste")
        self.tabs.addTab(drop, "Drop files")
        self.tabs.setCornerWidget(self.paste_clipboard, Qt.Corner.TopRightCorner)
        self.tabs.currentChanged.connect(lambda index: self.paste_clipboard.setVisible(index == 0))
        composer.addWidget(self.tabs)
        self.cancel = QPushButton("Cancel transfer")
        self.cancel.clicked.connect(self._cancel_transfer)
        composer.addWidget(self.cancel)

        row = QHBoxLayout()
        self.check = QPushButton("Check now / Latest")
        self.check.clicked.connect(self._refresh)
        self.poll = QCheckBox("Poll every 60 seconds")
        self.poll.setChecked(True)
        self.older = QPushButton("Older…")
        self.older.clicked.connect(lambda: self._refresh(self.next_before))
        for w in (self.check, self.poll, self.older):
            row.addWidget(w)
        browser.addLayout(row)
        self.listing = QTreeWidget()
        self.listing.setHeaderLabels(["Title / filename", "Type", "Bytes", "UTC timestamp"])
        self.listing.setRootIsDecorated(False)
        self.listing.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.listing.header().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.listing.setMinimumHeight(160)
        self.listing.currentItemChanged.connect(lambda *_: self._select())
        browser.addWidget(self.listing)
        row = QHBoxLayout()
        self.up, self.down = QPushButton("▲ Previous"), QPushButton("▼ Next")
        self.up.clicked.connect(lambda: self._step(-1))
        self.down.clicked.connect(lambda: self._step(1))
        self.delete = QPushButton("Delete from agent…")
        self.delete.clicked.connect(self._delete)
        for w in (self.up, self.down, self.delete):
            row.addWidget(w)
        browser.addLayout(row)
        self.detail = QLabel("Select an item to retrieve it.")
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setWordWrap(True)
        browser.addWidget(self.detail)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        browser.addWidget(self.preview, 1)
        row = QHBoxLayout()
        self.copy = QPushButton("Copy text")
        self.copy.clicked.connect(self._copy_text)
        self.save = QPushButton("Save copy…")
        self.save.clicked.connect(lambda: self._export(False))
        self.copy_file = QPushButton("Copy file…")
        self.copy_file.clicked.connect(lambda: self._export(True))
        self.drag = QPushButton("Drag saved copy")
        self.drag.pressed.connect(self._drag)
        for w in (self.copy, self.save, self.copy_file, self.drag):
            row.addWidget(w)
        browser.addLayout(row)
        self.clear_clipboard = QCheckBox("Clear my copied text after 60 seconds (clipboard history is not cleared)")
        self.clear_clipboard.setChecked(True)
        browser.addWidget(self.clear_clipboard)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([330, 650])
        layout.addWidget(split, 1)
        return layout

    def _idle(self):
        return self.pending is None and self.transfer is None and self._job is None

    def _list_pending(self):
        return (self.pending is not None and self.pending["operation"] == "list"
                and self.transfer is None and self._job is None)

    def _selected(self):
        item = self.listing.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def _buttons(self):
        busy = not self._idle()
        upload_ready = not busy or self._list_pending()
        for w in (self.send_text, self.choose_files, self.drop):
            w.setEnabled(upload_ready)
        self.check.setEnabled(not busy)
        for w in (self.listing, self.up, self.down):
            w.setEnabled(not busy or self._list_pending())
        self.older.setEnabled(not busy and self.next_before is not None)
        self.delete.setEnabled((not busy or self._list_pending()) and self._selected() is not None)
        self.cancel.setEnabled(busy and not self._list_pending())
        loaded = bool(self.loaded and self.loaded[0]["id"] == self._selected() and not busy)
        self.copy.setEnabled(loaded and self.loaded[0]["kind"] == "text")
        self.save.setEnabled(loaded)
        self.copy_file.setEnabled(loaded and self.loaded[0]["kind"] == "file")
        self.drag.setEnabled(loaded and self.exported is not None)

    def _send(self, operation, args, request_id):
        packet = Packet()
        packet.set_data({"handler": "cmd_service_request", "ts": time.time(), "content": {
            "service": "hive.drop_vault.request", "payload": {
                "target_universal_id": self.agent_uid, "session_id": self.session_id,
                "token": self.token, "request_id": request_id, "operation": operation, "args": args}}})
        self.bus.emit("outbound.message", session_id=self.session_id, channel="outgoing.command", packet=packet)

    def _request(self, operation, **args):
        if self.pending or not self._signals_connected:
            return
        self.pending = {"id": uuid.uuid4().hex, "operation": operation, "started": time.monotonic(),
                        "args": args, "retries": 0}
        self._buttons()
        try:
            self._send(operation, args, self.pending["id"])
        except Exception:
            self._failed("Request could not be sent. Check now to confirm server state before retrying.")

    def _callback(self, session_id, payload=None, **_):
        if session_id != self.session_id or not isinstance(payload, dict):
            return
        content = payload.get("content")
        if (isinstance(content, dict) and content.get("token") == self.token
                and content.get("agent_uid") == self.agent_uid):
            self.received.emit(content)

    @staticmethod
    def _entry(value):
        if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not re.fullmatch(r"[a-f0-9]{32}", value["id"]):
            raise ValueError("Invalid entry")
        if value.get("kind") not in ("text", "file") or type(value.get("size")) is not int or not 0 <= value["size"] <= MAX_BYTES:
            raise ValueError("Invalid size/type")
        if not isinstance(value.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", value["sha256"]):
            raise ValueError("Invalid checksum")
        for key, limit in (("title", 256), ("filename", 255), ("created", 80), ("notes", 4096)):
            field = value.get(key, "")
            if not isinstance(field, str) or len(field.encode("utf-8")) > limit:
                raise ValueError("Invalid metadata")
        return value

    def _receive(self, content):
        if not self._signals_connected or not self.pending or content.get("request_id") != self.pending["id"]:
            return
        operation = self.pending["operation"]
        if content.get("operation") != operation:
            return
        args = self.pending["args"]
        self.pending = None
        if content.get("ok") is not True:
            self._failed("Agent refused operation: " + str(content.get("error", "Unknown failure"))[:240])
            return
        try:
            if operation == "list":
                self._show_listing(content)
                self.page_before = args.get("before")
            elif operation == "begin":
                if content.get("object_id") != self.transfer["id"]:
                    raise ValueError("Mismatched upload")
                if content.get("committed") is True:
                    self._uploaded()
                else:
                    self._next_chunk(content.get("offset"))
            elif operation == "chunk":
                self._next_chunk(content.get("offset"))
            elif operation == "commit":
                entry = self._entry(content.get("entry"))
                if entry["id"] != self.transfer["id"] or entry["sha256"] != self.transfer["sha256"]:
                    raise ValueError("Mismatched commit")
                self._uploaded()
            elif operation == "read":
                self._read_chunk(content, args)
            elif operation == "delete":
                if content.get("deleted") is not True:
                    raise ValueError("Deletion not acknowledged")
                self.loaded = self.exported = None
                self.preview.clear()
                self._refresh()
                if content.get("cleanup_pending"):
                    self.status.setText("Removed from listing; encrypted-object deletion is pending a server retry.")
        except Exception:
            self._failed("Invalid or incomplete agent response; nothing was copied or exported. Check now before retrying.")
        self._buttons()

    def _refresh(self, before=None, *, background=False):
        # clicked(bool) must not be interpreted as a paging cursor.
        if type(before) is bool:
            before = None
        if not self._idle():
            return
        if not background:
            self.status.setText("Checking encrypted inbox…")
        self._last_poll = time.monotonic()
        self._request("list", **({"before": before} if before is not None else {}))

    def _show_listing(self, content):
        entries = content.get("entries")
        if not isinstance(entries, list) or len(entries) > 20:
            raise ValueError("Invalid listing")
        checked = [self._entry(entry) for entry in entries]
        if len({entry["id"] for entry in checked}) != len(checked):
            raise ValueError("Duplicate entry")
        cursor = content.get("next_before")
        if cursor is not None and (type(cursor) is not int or cursor < 1):
            raise ValueError("Invalid cursor")
        selected = self._selected()
        self.entries = {entry["id"]: entry for entry in checked}
        self.next_before = cursor
        self.listing.blockSignals(True)
        self.listing.clear()
        for entry in checked:
            title = entry["title"] or entry["filename"] or "Untitled paste"
            item = QTreeWidgetItem([title, entry["kind"], str(entry["size"]), entry["created"]])
            item.setData(0, Qt.ItemDataRole.UserRole, entry["id"])
            self.listing.addTopLevelItem(item)
            if entry["id"] == selected:
                self.listing.setCurrentItem(item)
        self.listing.blockSignals(False)
        if selected not in self.entries:
            self.loaded = self.exported = None
            self.preview.clear()
            self.detail.setText("Select an item to retrieve it.")
        cleanup = content.get("pending_deletions", 0)
        if type(cleanup) is not int or cleanup < 0:
            raise ValueError("Invalid cleanup status")
        self.status.setText(f"Inbox checked · {len(checked)} shown · {content.get('total_items', '?')} total. "
                            + (f"Encrypted-object deletions awaiting cleanup: {cleanup}." if cleanup
                               else "No item is opened automatically."))

    def _step(self, delta):
        index = self.listing.indexOfTopLevelItem(self.listing.currentItem())
        target = max(0, min(self.listing.topLevelItemCount()-1, index+delta))
        if target >= 0:
            self.listing.setCurrentItem(self.listing.topLevelItem(target))

    def _select(self):
        if self._list_pending():
            # An interactive selection takes priority over a background list.
            # Its late callback is ignored by the request-id check.
            self.pending = None
        elif not self._idle():
            return
        self._last_poll = time.monotonic()
        selected = self._selected()
        self.loaded = self.exported = None
        self.preview.clear()
        if selected in self.entries:
            entry = self.entries[selected]
            self.detail.setText("Retrieving selected object…")
            self.transfer = {"mode": "read", "id": selected, "entry": entry, "data": bytearray()}
            self._request("read", object_id=selected, offset=0)
        self._buttons()

    def _read_chunk(self, content, args):
        entry = self._entry(content.get("entry"))
        transfer = self.transfer
        if not transfer or transfer["mode"] != "read" or entry["id"] != transfer["id"]:
            raise ValueError("Stale read")
        if entry["sha256"] != transfer["entry"]["sha256"] or entry["size"] != transfer["entry"]["size"]:
            raise ValueError("Object changed")
        if content.get("offset") != args["offset"] or args["offset"] != len(transfer["data"]):
            raise ValueError("Invalid offset")
        encoded = content.get("data")
        if not isinstance(encoded, str) or len(encoded) > 4*((CHUNK+2)//3):
            raise ValueError("Invalid chunk")
        block = base64.b64decode(encoded, validate=True)
        if len(block) > CHUNK or len(transfer["data"]) + len(block) > entry["size"]:
            raise ValueError("Invalid chunk length")
        transfer["data"].extend(block)
        if content.get("eof") is True:
            data = bytes(transfer["data"])
            if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("Checksum mismatch")
            text = data.decode("utf-8") if entry["kind"] == "text" else None
            self.loaded = (entry, data)
            self.transfer = None
            self.detail.setText(f"{entry['created']} · {entry['size']} bytes · SHA-256 verified\nNotes: {entry.get('notes', '')}")
            if entry["kind"] == "text":
                self.preview.setPlainText(text)
            else:
                self.preview.setPlainText("File received in memory. Use Save copy or Copy file to export it; no plaintext file has been created yet.")
            self.status.setText("Retrieved and verified. Copying/exporting is your choice.")
        else:
            if not block:
                raise ValueError("No read progress")
            self.status.setText(f"Retrieving {len(transfer['data'])} / {entry['size']} bytes…")
            self._request("read", object_id=entry["id"], offset=len(transfer["data"]))

    def _draft_text(self, text):
        if len(text.encode("utf-8")) > MAX_BYTES:
            self.status.setText("Text exceeds the 1 MiB limit (UTF-8 bytes).")
            self._set_paste_feedback("error", "Text exceeds the 1 MiB limit; nothing was uploaded.")
            self.drop.set_feedback("error", "Text exceeds the 1 MiB limit; nothing was uploaded.")
            return
        self.paste.setPlainText(text)
        self.tabs.setCurrentIndex(0)

    def _set_paste_feedback(self, state, message):
        colors = {"draft": "#65b8de", "busy": "#d5a83e", "saved": "#28c787", "error": "#e07171"}
        self.paste_feedback.setStyleSheet(f"QLabel {{ color: {colors[state]}; padding: 4px; }}")
        self.paste_feedback.setText(message)

    def _paste_draft_changed(self):
        if self.transfer is not None and self.transfer.get("mode") == "upload":
            return
        if self.paste.toPlainText():
            self._set_paste_feedback("draft", "Draft changed · not uploaded. Press Upload Text when ready.")

    def _upload_text(self):
        data = self.paste.toPlainText().encode("utf-8")
        if not data:
            self.status.setText("Paste some text first.")
            self._set_paste_feedback("error", "Paste some text first; nothing was uploaded.")
            return
        self._upload(data, "text", "")

    def _upload(self, data, kind, filename, sha256=None, source_path=None):
        if self._list_pending():
            self.pending = None  # An upload takes priority over a stale listing.
        if not self._idle():
            return
        if len(data) > MAX_BYTES:
            if kind == "text":
                self._set_paste_feedback("error", "Text exceeds the 1 MiB limit; nothing was uploaded.")
            self._failed("Item exceeds the 1 MiB limit; use a smaller file or paste.")
            return
        if len(self.title.text().encode()) > 256 or len(self.notes.toPlainText().encode()) > 4096:
            if kind == "text":
                self._set_paste_feedback("error", "Title or notes exceed their size limit; nothing was uploaded.")
            self._failed("Title or notes exceed their size limit.")
            return
        object_id = uuid.uuid4().hex
        self.transfer = {"mode": "upload", "id": object_id, "data": data, "kind": kind,
                         "sha256": sha256 or hashlib.sha256(data).hexdigest(), "sent_end": 0,
                         "draft": self.paste.toPlainText() if kind == "text" else None,
                         "source_path": source_path, "filename": filename}
        self.status.setText("Starting encrypted upload…")
        if kind == "file":
            self.drop.set_feedback("busy", f"Uploading {filename}…\nPlease wait for saved confirmation.")
        else:
            self._set_paste_feedback("busy", "Sending text to agent · waiting for upload acknowledgement…")
        self._request("begin", object_id=object_id, kind=kind, title=self.title.text(), filename=filename,
                      notes=self.notes.toPlainText(), size=len(data), sha256=self.transfer["sha256"])

    def _next_chunk(self, offset):
        transfer = self.transfer
        if not transfer or type(offset) is not int or offset != transfer["sent_end"]:
            raise ValueError("Unexpected upload offset")
        data = transfer["data"]
        if offset == len(data):
            self.status.setText("Publishing encrypted object and catalogue…")
            if transfer["kind"] == "file":
                self.drop.set_feedback("busy", "Upload sent · waiting for agent to confirm encrypted save…")
            else:
                self._set_paste_feedback("busy", "Text sent · waiting for encrypted-save confirmation from agent…")
            self._request("commit", object_id=transfer["id"])
            return
        block = data[offset:offset+CHUNK]
        transfer["sent_end"] = offset+len(block)
        self.status.setText(f"Uploading {offset} / {len(data)} bytes…")
        if transfer["kind"] == "file":
            self.drop.set_feedback("busy", f"Uploading {transfer['filename']} · {offset} / {len(data)} bytes…")
        else:
            self._set_paste_feedback("busy", f"Sending text · {offset} / {len(data)} bytes acknowledged…")
        self._request("chunk", object_id=transfer["id"], offset=offset, data=base64.b64encode(block).decode("ascii"))

    def _uploaded(self):
        transfer = self.transfer
        newer_text_draft = transfer["kind"] == "text" and self.paste.toPlainText() != transfer["draft"]
        if transfer["kind"] == "text" and self.paste.toPlainText() == transfer["draft"]:
            self.paste.clear()
        if transfer["kind"] == "text":
            self._set_paste_feedback("saved", "Text saved encrypted on agent."
                                     + (" Newer draft is still unsent." if newer_text_draft else " Draft cleared."))
        if transfer["kind"] == "file":
            if transfer["source_path"]:
                self._recent_file_uploads[(transfer["source_path"], transfer["sha256"])] = time.monotonic()
            self.drop.set_feedback("saved", f"Saved encrypted on agent: {transfer['filename']}\nReady for another drop.")
        self.transfer = None
        self.status.setText("Saved encrypted on agent.")
        if self._queue:
            self._start_file()
        else:
            self._refresh()

    def _choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Upload files to Drop Vault")
        self._queue_files(paths)

    def _queue_files(self, paths):
        if self._list_pending():
            self.pending = None  # Ignore the late list reply after the upload starts.
        if not self._idle():
            self.status.setText("A transfer is already running; wait or cancel it first.")
            self.drop.set_feedback("busy", "Transfer already running · wait for saved confirmation.")
            return
        if not paths or len(paths) > 16:
            self.status.setText("Choose between 1 and 16 files at a time.")
            self.drop.set_feedback("error", "Choose between 1 and 16 files; nothing was uploaded.")
            return
        self._queue = list(paths)
        self.drop.set_feedback("busy", f"Drop received · preparing {len(paths)} file(s)…\nPlease wait; do not drop again.")
        self._start_file()

    def _start_file(self):
        path = self._queue.pop(0)
        self.drop.set_feedback("busy", f"Reading {Path(path).name}…\nPlease wait for saved confirmation.")
        self.status.setText("Reading local file in background…")
        self._local_job("read", path)

    def _local_job(self, mode, path, data=None, copy_file=False):
        self._local_generation += 1
        generation = self._local_generation
        job = FileJob(mode, path, data)
        self._job = job
        job.completed.connect(lambda result: self._local_done(generation, mode, result, copy_file))
        job.failed.connect(lambda message: self._local_error(generation, message))
        job.launch()
        self._buttons()

    def _local_error(self, generation, message):
        if generation != self._local_generation:
            return
        if self._job is not None and self._job.mode == "read":
            self.drop.set_feedback("error", "File could not be read · nothing was uploaded.")
        self._job = None
        self._failed(message)

    def _local_done(self, generation, mode, result, copy_file):
        if generation != self._local_generation or not self._signals_connected:
            return
        source_path = str(Path(self._job.path).absolute()) if mode == "read" else None
        self._job = None
        if mode == "read":
            now = time.monotonic()
            self._recent_file_uploads = {key: at for key, at in self._recent_file_uploads.items() if now-at < 10}
            if (source_path, result["sha256"]) in self._recent_file_uploads:
                self.drop.set_feedback("notice", f"Already saved just now: {result['filename']}\nRepeat drop ignored.")
                self.status.setText("Repeat drop ignored; the same file was saved less than 10 seconds ago.")
                if self._queue:
                    self._start_file()
                else:
                    self._buttons()
                return
            self._upload(result["data"], "file", result["filename"], result["sha256"], source_path)
        else:
            self.exported = result["path"]
            if copy_file:
                QApplication.clipboard().setMimeData(self._file_mime())
            self.status.setText("Local copy saved" + (" and copied to clipboard." if copy_file else ". You can drag the saved copy."))
            self._buttons()

    def _export(self, copy_file):
        if not self.loaded or not self._idle():
            return
        entry, data = self.loaded
        name = entry["filename"] if entry["kind"] == "file" else "paste.txt"
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "drop.bin"
        path, _ = QFileDialog.getSaveFileName(self, "Save a local plaintext copy (not encrypted by Drop Vault)", name)
        if path:
            self._local_job("write", path, data, copy_file)

    def _file_mime(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self.exported)])
        mime.setData('application/x-qt-windows-mime;value="Preferred DropEffect"', b"\x01\x00\x00\x00")
        return mime

    def _drag(self):
        if self.exported and Path(self.exported).is_file():
            drag = QDrag(self)
            drag.setMimeData(self._file_mime())
            drag.exec(Qt.DropAction.CopyAction)

    def _copy_text(self):
        if not self.loaded or self.loaded[0]["kind"] != "text":
            return
        mime = QMimeData()
        marker = uuid.uuid4().hex.encode("ascii")
        mime.setText(self.loaded[1].decode("utf-8"))
        mime.setData("application/x-phoenix-drop-vault", marker)
        QApplication.clipboard().setMimeData(mime)
        if self.clear_clipboard.isChecked():
            # No bound-panel callback: ownership-checked expiry survives hiding
            # or closing the panel, but never clears somebody else's clipboard.
            QTimer.singleShot(60000, lambda: _expire_clipboard(marker))
        self.status.setText("Text copied. System clipboard history may keep a copy.")

    def _delete(self):
        object_id = self._selected()
        if not object_id or (not self._idle() and not self._list_pending()):
            return
        if QMessageBox.question(self, "Delete shared drop?", "Delete this item from the agent for every Phoenix instance? Local copies and clipboard history are not removed.",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            if self._list_pending():
                self.pending = None
            self._last_poll = time.monotonic()
            self.status.setText("Deleting from agent…")
            self._request("delete", object_id=object_id)

    def _failed(self, message):
        if self.transfer is not None and self.transfer.get("mode") == "upload" and self.transfer.get("kind") == "text":
            self._set_paste_feedback("error", message)
        if (self.transfer is not None and self.transfer.get("mode") == "upload") or self._queue:
            self.drop.set_feedback("error", "Upload not confirmed · check the inbox before trying again.")
        self.pending = self.transfer = None
        self._queue.clear()
        self.status.setText(message)
        self._buttons()

    def _cancel_transfer(self):
        transfer = self.transfer
        file_transfer = ((transfer is not None and transfer.get("mode") == "upload"
                          and transfer.get("kind") == "file")
                         or (self._job is not None and self._job.mode == "read")
                         or bool(self._queue))
        if transfer and transfer["mode"] == "upload":
            try:
                self._send("cancel", {"object_id": transfer["id"]}, uuid.uuid4().hex)
            except Exception:
                pass  # Unpublished upload buffers expire on the agent.
        self._local_generation += 1
        was_exporting = self._job is not None and self._job.mode == "write"
        self._job = None
        self._failed("Stopped locally. Check now to confirm whether a commit reached the agent."
                     + (" The requested local export may still finish." if was_exporting else ""))
        if file_transfer:
            self.drop.set_feedback("notice", "Transfer stopped locally · check the inbox before dropping again.")

    def _tick(self):
        if self.pending and time.monotonic() - self.pending["started"] > 30:
            if self.pending["retries"] == 0:
                self.pending["retries"] = 1
                self.pending["started"] = time.monotonic()
                self.status.setText(f"No agent reply yet; retrying {self.pending['operation']} once…")
                if (self.transfer is not None and self.transfer.get("mode") == "upload"
                        and self.transfer.get("kind") == "text"):
                    self._set_paste_feedback(
                        "busy", f"No agent acknowledgement for {self.pending['operation']} yet · retrying once…")
                try:
                    self._send(self.pending["operation"], self.pending["args"], self.pending["id"])
                except Exception:
                    self._failed("Retry could not be sent. Check now before retrying an upload.")
            else:
                self._failed("No acknowledgement. Check now to confirm server state; do not assume the upload failed or succeeded.")
        elif self.poll.isChecked() and self._idle() and time.monotonic()-self._last_poll >= 60:
            self._refresh(self.page_before, background=True)

    def _connect_signals(self):
        if not self._signals_connected:
            self.bus.on("inbound.verified.drop_vault.result", self._callback)
            self._signals_connected = True

    def _disconnect_signals(self):
        if self._signals_connected:
            self.bus.off("inbound.verified.drop_vault.result", self._callback)
            self._signals_connected = False

    def _on_show(self):
        self.timer.start()
        self._refresh()

    def _on_hide(self):
        self.timer.stop()
        self._cancel_transfer()
        self.loaded = self.exported = None
        self.preview.clear()
        self._buttons()

    def _on_close(self):
        self._cancel_transfer()
        self.loaded = self.exported = None
        self.preview.clear()
        self.paste.clear()
        self.notes.clear()
        self.title.clear()

    def get_panel_buttons(self):
        return [PanelButton("📥", "Drop Vault", lambda: self.session_window.show_specialty_panel(self))]


def _expire_clipboard(marker):
    clipboard = QApplication.clipboard()
    mime = clipboard.mimeData()
    if mime and bytes(mime.data("application/x-phoenix-drop-vault")) == marker:
        clipboard.clear()
