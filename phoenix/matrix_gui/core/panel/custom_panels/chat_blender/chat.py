from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QHBoxLayout, QPushButton, QLineEdit, QLabel
)
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
import uuid, time

class Chat(PhoenixPanelInterface):
    cache_panel = True

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self.setLayout(self._build_layout())
        self._connect_signals()
        self.auto_scroll = True

    def _build_layout(self):
        layout = QVBoxLayout()

        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setStyleSheet("font-family: Consolas, monospace;")
        layout.addWidget(QLabel("🔄 Encrypted Chat Log"))
        layout.addWidget(self.chat_log)

        entry_row = QHBoxLayout()
        self.input_field = QLineEdit()
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send_message)
        entry_row.addWidget(self.input_field)
        entry_row.addWidget(self.send_btn)

        layout.addLayout(entry_row)
        return layout

    def _send_message(self):
        text = self.input_field.text().strip()
        if not text:
            return

        token = str(uuid.uuid4())
        pk = Packet()
        pk.set_data({
            "handler": "cmd_service_request",
            "ts": time.time(),
            "content": {
                "service": "chat.blender.send",
                "payload": {
                    "session_id": self.session_id,
                    "token": token,
                    "msg": text,
                    "return_handler": "chat_blender_panel.update"
                }
            }
        })
        self.bus.emit("outbound.message", session_id=self.session_id, channel="outgoing.command", packet=pk)
        self.input_field.clear()

    def _connect_signals(self):
        scoped = f"inbound.verified.chat_blender_panel.update"
        self.bus.on(scoped, self._handle_output)

    def _handle_output(self, session_id, channel, source, payload, **_):
        try:
            data = payload.get("content", {})
            msg = data.get("msg", "")
            origin = data.get("origin", "?")
            self.chat_log.append(f"[{origin}] {msg}")
            if self.auto_scroll:
                self.chat_log.moveCursor(self.chat_log.textCursor().End)
        except Exception as e:
            print(f"[CHAT_PANEL][ERROR] {e}")

    def get_panel_buttons(self):
        return []
