from __future__ import annotations
import socket
from typing import Dict, Any, Optional
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QTabWidget
from PyQt5.QtCore import Qt, QTimer
from matrix_gui.core.panel.agent_tree.agent_tree import PhoenixAgentTree
from matrix_gui.core.event_bus import EventBus
from matrix_gui.config.boot.globals import get_sessions
from PyQt5.QtWidgets import QSplitter, QTextEdit, QGroupBox, QVBoxLayout, QSizePolicy

# Pinned global session constant
GLOBAL_SESSION_ID = "GLOBAL"

class PhoenixTabStack(QWidget):
    """
    Tab stack with a pinned Global tab at index 0 that shows all traffic,
    and additional tabs bound to specific session_ids.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        self.layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget(self)
        self.layout.addWidget(self.tab_widget)

        # maps: tab_index -> session_id
        self._tab_sessions: Dict[int, str] = {}
        # optional: tab_index -> widget w/ .console QTextEdit
        self._tab_widgets: Dict[int, Any] = {}

        # a shared console fallback if individual tab consoles aren't available
        self.feed_console = QTextEdit()
        self.feed_console.setReadOnly(True)
        self.feed_console.hide()

        self.feed_console.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # wire events
        EventBus.on("inbound.message", self._on_inbound_message)
        EventBus.on("connection.status", self._on_conn_status)

        EventBus.on("session.opened", self._on_session_opened)
        EventBus.on("session.closed", self._on_session_closed)

        EventBus.on("channel.status", self._on_channel_status)

        #close tab button
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._on_tab_close_requested)
        QTimer.singleShot(0, lambda: self.tab_widget.tabBar().setTabButton(0, self.tab_widget.tabBar().RightSide, None))

    def _on_channel_status(self, session_id, channel, status, info=None, **_):
        self.append_global(f"[{channel}] {status} :: sess={session_id} :: {info}")

    def _on_tab_close_requested(self, index: int):
        session_id = self._tab_sessions.get(index)
        if session_id and session_id != "GLOBAL":
            print(f"[UI] Closing tab for session {session_id}")
            ctx = get_sessions().get(session_id)
            if ctx:
                for channel_name, conn in list(ctx.channels.items()):
                    try:
                        if channel_name.endswith("-wss"):
                            # Tell connector to stop reconnect loop
                            EventBus.emit("session.closed", session_id=session_id)
                        if hasattr(conn, "close"):
                            conn.close()
                        else:
                            conn.shutdown(socket.SHUT_RDWR)
                            conn.close()
                    except Exception as e:
                        print(f"[UI] error closing channel {channel_name}: {e}")

                get_sessions().destroy(session_id)

            self.tab_widget.removeTab(index)
            self._tab_sessions.pop(index, None)
            self._tab_widgets.pop(index, None)


    def get_active_session_id(self) -> str | None:
        """
        Returns the session_id of the currently active tab,
        or None if the active tab is not bound to a session.
        """
        idx = self.tab_widget.currentIndex()
        return self._tab_sessions.get(idx)

    def _on_session_opened(self, session_id: str, group: dict, **_):
        QTimer.singleShot(0, lambda: self._add_tab_safe(session_id, group))

    def _add_tab_safe(self, session_id, group):
        if self._find_tab_by_session(session_id) is not None:
            return
        gname = group.get("name") or group.get("id") or "Session"
        label = f"{gname} (deployment)"
        self.add_session_tab(session_id, label=label)

    def _on_session_closed(self, session_id: str, **_):
        idx = self._find_tab_by_session(session_id)
        if idx is None or idx == 0:
            return
        self.tab_widget.removeTab(idx)
        self._tab_sessions.pop(idx, None)
        self._tab_widgets.pop(idx, None)
        print(f"[UI] Closed tab for {session_id}")

    def _find_tab_by_session(self, session_id: str):
        for idx, sid in self._tab_sessions.items():
            if sid == session_id:
                return idx
        return None

    def append_global(self, text: str):
        QTimer.singleShot(0, lambda: self._append_global_safe(text))

    def _append_global_safe(self, text: str):
        try:
            self._tab_widgets[0].console.append(text)
        except Exception:
            self.feed_console.append(text)

    def append_global_packet(self, payload: dict):
        QTimer.singleShot(0, lambda: self._append_global_packet_safe(payload))

    def _append_global_packet_safe(self, payload: dict):
        try:
            self._tab_widgets[0].console.append(self._fmt_packet(payload))
        except Exception:
            self.feed_console.append(self._fmt_packet(payload))

    def add_session_tab(self, session_id, widget_cls=None, label=None):
        if widget_cls is None:
            widget_cls = PhoenixAgentTree

        # Outer horizontal splitter

        splitter = QSplitter(Qt.Horizontal, self.tab_widget)
        w = widget_cls(bound_session_id=session_id, parent=splitter)
        splitter.addWidget(w)


        # Right: log panel
        log_box = QGroupBox("📡 Agent Intel Logs")
        log_box.setStyleSheet("""
            QGroupBox {
                border: 1.2px solid #33384c;
                border-radius: 8px;
                margin-top: 8px;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
                color: #4fc3f7;
                background-color: #232336;
                font-weight: bold;
            }
            QGroupBox:title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 6px 0 6px;
                background: #232336;
            }
        """)
        log_layout = QVBoxLayout(log_box)
        log_console = QTextEdit()
        log_console.setReadOnly(True)
        log_console.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a22;
                color: #e0e0e0;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
                border: 1px solid #33384c;
                border-radius: 8px;
                padding: 8px;
            }
            QTextEdit:focus {
                border: 1.5px solid #0078d7;
                background: #21213c;
            }
        """)
        log_layout.addWidget(log_console)


        log_box.setMinimumHeight(150)  # always usable
        log_box.setMinimumWidth(150)
        log_console.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        splitter.addWidget(log_box)
        splitter.setSizes([900, 400])
        splitter.setStretchFactor(0, 3)  # Tree+Detail gets 3x space
        splitter.setStretchFactor(1, 1)  # Logs get 1x

        idx = self.tab_widget.addTab(splitter, label or session_id[:6])
        self._tab_sessions[idx] = session_id
        self._tab_widgets[idx] = w
        w.console = log_console  # if you want logs attached
        self.tab_widget.setCurrentIndex(idx)

        print(f"[UI] addTab returned index {idx} for {session_id}")
        return idx

    def display_feed(self, payload: dict):
        QTimer.singleShot(0, lambda: self._display_feed_safe(payload))

    def _display_feed_safe(self, payload: dict):
        try:
            active_idx = self.tab_widget.currentIndex()
            sess_filter = self._tab_sessions.get(active_idx)
            sess_id = payload.get("session_id") or payload.get("sess") or ""
            if sess_filter in (GLOBAL_SESSION_ID, None):
                self._tab_widgets[active_idx].console.append(self._fmt_packet(payload))
                return
            if sess_id == sess_filter:
                self._tab_widgets[active_idx].console.append(self._fmt_packet(payload))
        except Exception:
            self.feed_console.append(self._fmt_packet(payload))

    def _on_inbound_message(self, session_id: str, channel: str, source: str, payload: dict, ts: float, **_):
        # 1) always tee to Global
        global_line = dict(payload)
        global_line.update({"session_id": session_id, "channel": channel, "source": source, "ts": ts})
        QTimer.singleShot(0, lambda: self._append_global_packet_safe(global_line))

        # 2) allow the active tab to consume if it matches its filter
        QTimer.singleShot(0, lambda: self._display_feed_safe(global_line))


    def _on_conn_status(self, session_id: str, channel: str, status: str, info: dict, **_):
        self.append_global(f"[{channel}] {status} :: sess={session_id} :: {info}")

    # ---------------- Helpers ----------------
    def _make_tab_widget(self, title: str) -> QWidget:
        w = QWidget(self)
        l = QVBoxLayout(w)
        console = QTextEdit(w)
        console.setReadOnly(True)
        l.addWidget(console)
        # keep a handle for appenders
        w.console = console  # type: ignore[attr-defined]
        w.setObjectName(f"tab_{title}")
        return w

    def _fmt_packet(self, payload: dict) -> str:
        import time as _t, json as _j
        ts = _t.strftime("%H:%M:%S", _t.localtime(payload.get("ts") or _t.time()))
        sess = payload.get("session_id") or "?"
        ch   = payload.get("channel") or payload.get("via") or "-"
        src  = payload.get("source") or "border"
        # show either decrypted inner content (if present) or the payload
        body = payload.get("content", payload)
        try:
            snippet = _j.dumps(body, separators=(",", ":"), sort_keys=True)[:240]
        except Exception:
            snippet = str(body)[:240]
        return f"[{ts}] ({ch}) {src} » sess={sess} :: {snippet}"
