from __future__ import annotations
from typing import Dict, Any, Optional
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QTabWidget
from PyQt5.QtCore import Qt, QTimer
from matrix_gui.core.panel.agent_tree.agent_tree import PhoenixAgentTree
from matrix_gui.core.event_bus import EventBus
from matrix_gui.config.boot.globals import get_sessions
import socket

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
        """
        group follows the new scheme's connection_group shape:
          { "id": "group:...", "name": "...", "https": {"host": "...", "port": 443, ...}, "wss": {...} }
        """
        # if a tab already exists for this session, bail
        if self._find_tab_by_session(session_id) is not None:
            return

        gname = group.get("name") or group.get("id") or "Session"
        label = f"{gname} (deployment)"
        self.add_session_tab(session_id, label=label)

    def _on_session_closed(self, session_id: str, **_):
        idx = self._find_tab_by_session(session_id)
        if idx is None or idx == 0:
            # don't close Global
            return
        self.tab_widget.removeTab(idx)
        self._tab_sessions.pop(idx, None)
        self._tab_widgets.pop(idx, None)

    def _find_tab_by_session(self, session_id: str):
        for idx, sid in self._tab_sessions.items():
            if sid == session_id:
                return idx
        return None

    def append_global(self, text: str):
        try:
            self._tab_widgets[0].console.append(text)
        except Exception:
            self.feed_console.append(text)

    def append_global_packet(self, payload: dict):
        try:
            self._tab_widgets[0].console.append(self._fmt_packet(payload))
        except Exception:
            self.feed_console.append(self._fmt_packet(payload))

    # ---------------- Per-session tabs ----------------
    def add_session_tab(self, session_id, widget_cls=None, label=None):
        if widget_cls is None:

            widget_cls = PhoenixAgentTree

        w = widget_cls(bound_session_id=session_id, parent=self.tab_widget)
        idx = self.tab_widget.addTab(w, label or session_id[:6])
        self._tab_sessions[idx] = session_id
        self._tab_widgets[idx] = w
        return idx

    def display_feed(self, payload: dict):
        """
        Called to display a payload in the active tab IF it matches the tab's session filter.
        """
        try:
            active_idx = self.tab_widget.currentIndex()
            sess_filter = self._tab_sessions.get(active_idx)
            sess_id = payload.get("session_id") or payload.get("sess") or ""
            if sess_filter in (GLOBAL_SESSION_ID, None):
                # Global or unknown mapping – just show it
                self._tab_widgets[active_idx].console.append(self._fmt_packet(payload))
                return
            if sess_id == sess_filter:
                self._tab_widgets[active_idx].console.append(self._fmt_packet(payload))
        except Exception:
            # fallback to shared console
            self.feed_console.append(self._fmt_packet(payload))

    # ---------------- Event bus handlers ----------------
    def _on_inbound_message(self, session_id: str, channel: str, source: str, payload: dict, ts: float, **_):
        # 1) always tee to Global
        global_line = dict(payload)
        global_line.update({"session_id": session_id, "channel": channel, "source": source, "ts": ts})
        self.append_global_packet(global_line)

        # 2) allow the active tab to consume if it matches its filter
        self.display_feed(global_line)

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
