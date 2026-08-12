import uuid, time
from PyQt6.QtWidgets import (
    QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QTextEdit, QCheckBox
)
from PyQt6.QtCore import QTimer, Qt
from collections import deque
from PyQt6.QtGui import QTextCursor

from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log


class LogWatcher(PhoenixPanelInterface):
    """
    LogWatcher panel: subscribes to inbound log digests and
    requests system log summaries from remote agents.
    """
    cache_panel = True

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        try:
            self.setLayout(self._build_layout())
            self._pending_digest = []
            self._last_token = None
            self._pending_lines = deque()
            self._flush_timer = QTimer(self)
            self._flush_timer.timeout.connect(self._flush_output)
            self._flush_timer.start(200)
            self._signals_connected = False
            self._timers.append(self._flush_timer)   # ⬅️ let the base class auto-clean it
        except Exception as e:
            emit_gui_exception_log("LogWatcher.__init__", e)

    # --- Required abstract methods from PhoenixPanelInterface ---
    def _connect_signals(self):

        """Attach bus listeners."""
        try:
            if not self._signals_connected:
                self._signals_connected=True
                scoped = "inbound.verified.logwatch_panel.update"
                self.bus.on(scoped, self._handle_output)
                print("[LOGWATCH] 🎧 Connected to", scoped)

        except Exception as e:
            emit_gui_exception_log("LogWatcher._connect_signals", e)

    def _disconnect_signals(self):
        """Detach bus listeners and clear any buffered lines."""
        pass

    def get_panel_buttons(self):
        """Provide toolbar buttons for this panel."""
        return [PanelButton("📜", "LogWatcher",
                lambda: self.session_window.show_specialty_panel(self))]

    # --- UI construction ---
    def _build_layout(self):
        layout = QVBoxLayout()

        title = QLabel("🔭 LogWatcher Digest Panel")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # --- Button Row ---
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Generate Digest")
        self.clear_btn = QPushButton("Clear")
        self.run_btn.clicked.connect(self._on_generate_clicked)
        self.clear_btn.clicked.connect(lambda: self.output_box.clear())
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.clear_btn)
        layout.addLayout(btn_row)

        # --- Collector Selection ---
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Collectors:"))
        self.collector_checkboxes = {}
        for name in ["httpd", "sshd", "dovecot", "fail2ban", "systemd", "postfix"]:
            cb = QCheckBox(name)
            cb.setChecked(name in ("httpd", "sshd"))
            bar.addWidget(cb)
            self.collector_checkboxes[name] = cb

        self.oracle_cb = QCheckBox("Oracle Analysis")
        self.oracle_cb.setChecked(False)
        bar.addWidget(self.oracle_cb)
        layout.addLayout(bar)

        # --- Output box ---
        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setPlaceholderText("Digest output will appear here...")
        layout.addWidget(self.output_box)
        return layout

    # --- Event-specific overrides (optional hooks) ---
    def _on_show(self):
        """Reset digest token when shown."""
        #self._last_token = None
        pass

    def _on_close(self):
        try:
            if self._signals_connected:
                scoped = "inbound.verified.logwatch_panel.update"
                self.bus.off(scoped, self._handle_output)
                print("[LOGWATCH] 🔕 Disconnected from", scoped)
                self._pending_lines.clear()
        except Exception as e:
            emit_gui_exception_log("LogWatcher._disconnect_signals", e)


    # --- Core logic ---
    def _on_generate_clicked(self):
        try:
            self._pending_lines.clear()
            self.output_box.clear()

            collectors = [name for name, cb in self.collector_checkboxes.items() if cb.isChecked()]
            use_oracle = self.oracle_cb.isChecked()
            self._last_token = str(uuid.uuid4())

            pk = Packet()
            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": "logwatch.generate.digest",
                    "payload": {
                        "collectors": collectors,
                        "use_oracle": use_oracle,
                        "session_id": self.session_id,
                        "token": self._last_token,
                        "return_handler": "logwatch_panel.update"
                    }
                }
            })

            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=pk
            )

            oracle_text = " 🧠 (Oracle enabled)" if use_oracle else ""
            self.output_box.append(f"🛰 Request sent for collectors: {', '.join(collectors)}{oracle_text}\n")
        except Exception as e:
            emit_gui_exception_log("LogWatcher._on_generate_clicked", e)

    def _handle_output(self, session_id, channel, source, payload, **_):
        content = payload.get("content", payload)
        lines = content.get("lines", [])
        token = content.get("token")
        if not lines:
            return
        if self._last_token and token and not token.startswith(self._last_token[:8]):
            print("[LOGWATCH] Skipping stale digest packet")
            return
        if not self.isVisible():
            return
        self._pending_lines.extend(lines)

    def _flush_output(self):
        if not self.isVisible() or not self._pending_lines:
            return
        try:
            chunk, max_chunk = [], 50
            while self._pending_lines and len(chunk) < max_chunk:
                chunk.append(self._pending_lines.popleft())
            self.output_box.append("\n".join(chunk))
            self.output_box.moveCursor(QTextCursor.MoveOperation.End)
        except Exception as e:
            emit_gui_exception_log("LogWatcher._flush_output", e)