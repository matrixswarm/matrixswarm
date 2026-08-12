import json
import time

from PyQt6.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QSizePolicy, QComboBox, QSpinBox, QMessageBox, QScrollArea, QGroupBox, QCheckBox, QLayout)
from PyQt6.QtGui import QColor
from PyQt6.QtCore import QRect, QSize, Qt, QPoint, QTimer
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet

import uuid
class CryptoAlertPanel(QWidget):
    cache_panel = True  # lets Phoenix cache it

    def __init__(self, session_id, bus=None, session_window=None):
        super().__init__(session_window)
        self.session_id = session_id
        self.bus = bus
        self.session_window = session_window
        self.setObjectName("crypto_alert_panel")

        # existing layout init here …
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(QLabel("📈 Crypto Alerts (Phoenix mode)"))

        # back button uses Phoenix home
        back_btn = QPushButton("⬅️ Back")
        back_btn.clicked.connect(self._go_home)
        self.layout.addWidget(back_btn)

        self.bus.on("some.response.signal", self._handle_crypto_response)


    def _go_home(self):
        if self.session_window:
            self.session_window.show_default_panel()

    def send_agent_payload(self, alert, partial=False):
        config = self.build_agent_config(alert)
        if partial:
            config["partial_config"] = True

        agent_packet = {
            "name": "crypto_alert",
            "universal_id": alert.get("universal_id"),
            "filesystem": {},
            "config": config,
            "source_payload": None
        }

        packet_data = {
            "handler": "cmd_inject_agents",
            "content": {
                "target_universal_id": "matrix",
                "subtree": agent_packet,
                "confirm_response": 1,
                "respond_to": "crypto_gui_1",
                "handler_role": "hive.rpc.route",
                "handler": "cmd_rpc_route",
                "response_handler": "rpc_result_inject_agent",
                "response_id": str(uuid.uuid4()),
                "push_live_config": partial
            }
        }

        pk = Packet()
        pk.set_data(packet_data)
        self.bus.emit("outbound.message", session_id=self.session_id, channel="outgoing.command", packet=pk)

        def send_crypto_service_packet(self, handler, content_dict):
            pk = Packet()
            pk.set_data({
                "handler": handler,
                "ts": time.time(),
                "content": content_dict
            })
            self.bus.emit("outbound.message", session_id=self.session_id, channel="outgoing.command", packet=pk)