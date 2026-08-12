# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import uuid, time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QLineEdit, QListWidget, QTextEdit, QSplitter
)
from PyQt6.QtGui import QTextCursor
from PyQt6.QtCore import QMetaObject, Qt, pyqtSlot, QTimer
from collections import deque

from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
from matrix_gui.modules.vault.services.vault_connection_singleton import VaultConnectionSingleton


class StreamViewer(PhoenixPanelInterface):
    cache_panel = True

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self.setLayout(self._build_layout())
        self._connect_signals()

        self.favorites = self.deployment.get("terminal_favorites", [])
        self._refresh_fav_list()

        self.auto_refresh = True
        self.scroll_btn.setChecked(True)
        self.scroll_btn.setText("Auto-Refresh: ON")

        self._pending_outputs = deque(maxlen=10)
        self.setAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange, True)

        # Prevent output_box from stealing focus
        self.output_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Periodically enforce focus to cmd_input after activation
        QTimer.singleShot(300, self._ensure_focus)

    # --- Layout ---
    def _build_layout(self):
        try:
            layout = QVBoxLayout()

            # === Favorites ===
            self.fav_list = QListWidget()
            self.fav_list.itemDoubleClicked.connect(self._populate_from_favorite)

            self.del_btn = QPushButton("Delete")
            self.edit_btn = QPushButton("Edit")
            self.del_btn.clicked.connect(self._delete_favorite)
            self.edit_btn.clicked.connect(self._edit_favorite)

            fav_btn_row = QHBoxLayout()
            fav_btn_row.addWidget(self.del_btn)
            fav_btn_row.addWidget(self.edit_btn)

            fav_container = QWidget()
            fav_layout = QVBoxLayout(fav_container)
            fav_layout.addWidget(QLabel("⭐ Favorites"))
            fav_layout.addWidget(self.fav_list)
            fav_layout.addLayout(fav_btn_row)

            # === Terminal output ===
            self.output_box = QTextEdit()
            self.output_box.setReadOnly(True)
            self.output_box.setObjectName("OutputBox")
            self.output_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)

            # === Splitter ===
            splitter = QSplitter(Qt.Orientation.Vertical)
            splitter.addWidget(fav_container)
            splitter.addWidget(self.output_box)
            splitter.setStretchFactor(1, 2)
            layout.addWidget(splitter)

            # === Command row ===
            self.cmd_input = QLineEdit()
            self.refresh_input = QLineEdit()
            self.cmd_input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.refresh_input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

            self.run_btn = QPushButton("Run")
            self.stop_btn = QPushButton("Stop")
            self.fav_btn = QPushButton("Add to Favorites")
            self.allowed_btn = QPushButton("List Allowed")
            self.scroll_btn = QPushButton("Auto-Scroll: ON")
            self.clear_btn = QPushButton("Clear")

            self.allowed_btn.clicked.connect(self._list_allowed)
            self.run_btn.clicked.connect(self._run_command)
            self.stop_btn.clicked.connect(self._stop_command)
            self.fav_btn.clicked.connect(self._add_to_favorites)
            self.scroll_btn.setCheckable(True)
            self.scroll_btn.clicked.connect(self._toggle_auto_scroll)
            self.clear_btn.clicked.connect(self._clear_output)

            cmd_row = QHBoxLayout()
            for w in [
                self.allowed_btn, self.cmd_input, self.refresh_input,
                self.run_btn, self.stop_btn, self.fav_btn,
                self.scroll_btn, self.clear_btn
            ]:
                cmd_row.addWidget(w)

            layout.addLayout(cmd_row)
            return layout
        except Exception as e:
            emit_gui_exception_log("StreamViewer._build_layout", e)

    # --- Required abstract methods from PhoenixPanelInterface ---
    def _connect_signals(self):
        """Attach bus listener for terminal stream updates."""
        try:
            scoped = "inbound.verified.terminal_panel.update"
            self.bus.on(scoped, self._handle_output)
            print(f"[STREAM] 🎧 Connected to {scoped}")
        except Exception as e:
            emit_gui_exception_log("StreamViewer._connect_signals", e)

    def _disconnect_signals(self):
        """Detach bus listener and clear any buffered outputs."""
        try:
            scoped = "inbound.verified.terminal_panel.update"
            self.bus.off(scoped, self._handle_output)
            print(f"[STREAM] 🔕 Disconnected from {scoped}")
            self._pending_outputs.clear()
        except Exception as e:
            emit_gui_exception_log("StreamViewer._disconnect_signals", e)

    def get_panel_buttons(self):
        """Return toolbar button for terminal viewer panel."""
        return [
            PanelButton("🖥️", "Terminal", lambda: self.session_window.show_specialty_panel(self))
        ]


    def _on_show(self):
        """Optional hook for when the panel becomes visible."""
        # Reassert keyboard focus on show
        QTimer.singleShot(0, self.cmd_input.setFocus)

    # --- Focus + Activation ---
    def event(self, e):
        if e.type() in (e.Type.WindowActivate, e.Type.FocusIn):
            if not self.cmd_input.hasFocus():
                self.cmd_input.setFocus()
        return super().event(e)

    def showEvent(self, event):
        super().showEvent(event)
        window = self.window()
        if window:
            window.activateWindow()
            window.raise_()
        QTimer.singleShot(0, self.cmd_input.setFocus)

    def _ensure_focus(self):
        if self.isVisible() and self.cmd_input and not self.cmd_input.hasFocus():
            self.cmd_input.setFocus()
            QTimer.singleShot(250, self._ensure_focus)

    # --- CRUD Favorites ---
    def _refresh_fav_list(self):
        try:
            self.fav_list.clear()
            for fav in self.favorites:
                self.fav_list.addItem(f"{fav['cmd']} (refresh={fav.get('refresh', 0)})")
        except Exception as e:
            emit_gui_exception_log("StreamViewer._refresh_fav_list", e)

    def _add_to_favorites(self):
        try:
            cmd = self.cmd_input.text().strip()
            refresh = self.refresh_input.text().strip() or "0"
            if not cmd:
                return

            new_entry = {"cmd": cmd, "refresh": int(refresh)}
            self.favorites.append(new_entry)

            # Use the vault singleton instead of direct deployment access
            vault = VaultConnectionSingleton.get()
            vault.update_field("terminal_favorites", self.favorites)

            self._refresh_fav_list()
            print("[STREAM] ⭐ Favorite added and vault updated")
        except Exception as e:
            emit_gui_exception_log("StreamViewer._add_to_favorites", e)

    def _populate_from_favorite(self, item):
        try:
            idx = self.fav_list.row(item)
            fav = self.favorites[idx]
            self.cmd_input.setText(fav["cmd"])
            self.refresh_input.setText(str(fav.get("refresh", 0)))
        except Exception as e:
            emit_gui_exception_log("StreamViewer._populate_from_favorite", e)

    def _delete_favorite(self):
        try:
            row = self.fav_list.currentRow()
            if 0 <= row < len(self.favorites):
                self.favorites.pop(row)

                vault = VaultConnectionSingleton.get()
                vault.update_field("terminal_favorites", self.favorites)

                self._refresh_fav_list()
                print("[STREAM] ❌ Favorite deleted and vault updated")
        except Exception as e:
            emit_gui_exception_log("StreamViewer._delete_favorite", e)

    def _edit_favorite(self):
        try:
            row = self.fav_list.currentRow()
            if row >= 0:
                fav = self.favorites[row]
                self.cmd_input.setText(fav["cmd"])
                self.refresh_input.setText(str(fav.get("refresh", 0)))
                self._editing_row = row
        except Exception as e:
            emit_gui_exception_log("StreamViewer._edit_favorite", e)

    # --- Command Actions ---
    def _run_command(self):
        try:
            cmd = self.cmd_input.text().strip()
            refresh = int(self.refresh_input.text().strip() or 0)
            if not cmd:
                return
            token = str(uuid.uuid4())

            pk = Packet()
            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": "terminal.stream.start",
                    "payload": {
                        "command": cmd,
                        "refresh_sec": refresh,
                        "session_id": self.session_id,
                        "token": token,
                        "return_handler": "terminal_panel.update"
                    }
                }
            })
            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=pk)
        except Exception as e:
            emit_gui_exception_log("StreamViewer._run_command", e)

    def _stop_command(self):
        try:
            token = self._last_token = str(uuid.uuid4())
            pk = Packet()
            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": "terminal.stream.stop",
                    "payload": {
                        "session_id": self.session_id,
                        "token": token,
                        "return_handler": "terminal_panel.update",
                        "stop": True
                    }
                }
            })
            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=pk)
        except Exception as e:
            emit_gui_exception_log("StreamViewer._stop_command", e)

    def _handle_output(self, session_id, channel, source, payload, **_):
        try:
            if not payload:
                return
            data = payload.get("content") or {}
            output = str(data.get("output") or "")
            token = data.get("token") or ""
            clear_needed = (
                self.auto_refresh and token and
                getattr(self, "_last_token", None) != token
            )
            self._pending_outputs.append((output, clear_needed))
            QMetaObject.invokeMethod(
                self, "_flush_pending_output",
                Qt.ConnectionType.QueuedConnection
            )
        except Exception as e:
            emit_gui_exception_log("StreamViewer._handle_output", e)

    @pyqtSlot()
    def _flush_pending_output(self):
        try:
            if not self._pending_outputs:
                return
            output, clear_needed = self._pending_outputs.pop()
            self._pending_outputs.clear()
            if clear_needed:
                self.output_box.clear()
            self.output_box.append(output)
            if self.auto_refresh:
                self.output_box.moveCursor(QTextCursor.MoveOperation.End)
            if self.isVisible():
                QTimer.singleShot(150, self.cmd_input.setFocus)
        except Exception as e:
            emit_gui_exception_log("StreamViewer._flush_pending_output", e)

    # --- Misc ---
    def _toggle_auto_scroll(self):
        try:
            self.auto_refresh = self.scroll_btn.isChecked()
            self.scroll_btn.setText("Auto-Refresh: ON" if self.auto_refresh else "Auto-Refresh: OFF")
        except Exception as e:
            emit_gui_exception_log("StreamViewer._toggle_auto_scroll", e)

    def _clear_output(self):
        try:
            self.output_box.clear()
        except Exception as e:
            emit_gui_exception_log("StreamViewer._clear_output", e)

    def _list_allowed(self):

        try:
            token = str(uuid.uuid4())
            pk = Packet()
            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": "terminal.allowed.list",
                    "payload": {
                        "session_id": self.session_id,
                        "token": token,
                        "return_handler": "terminal_panel.update"
                    }
                }
            })
            self.output_box.clear()
            self.output_box.append("Fetching allowed commands...\n")
            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=pk)
        except Exception as e:
            emit_gui_exception_log("StreamViewer._list_allowed", e)
