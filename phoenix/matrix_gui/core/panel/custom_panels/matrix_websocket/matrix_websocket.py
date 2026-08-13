# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Commander Edition – Matrix HTTPS Perimeter Panel
# Modeled directly after MatrixWebsocketPanel

import time, json
from PyQt6.QtCore import QMetaObject, Q_ARG, Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QTextEdit, QMessageBox
)

from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.core.panel.control_bar import PanelButton

class MatrixWebsocket(PhoenixPanelInterface):
    cache_panel = True

    def __init__(self, session_id, bus, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self.node = node
        self.setLayout(self._build_ui())

    # ----------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel("🛰️ Matrix Websocket — Perimeter Control"))

        # STATE: OPEN / LOCKDOWN
        row_state = QHBoxLayout()
        row_state.addWidget(QLabel("Perimeter State:"))
        self.state_combo = QComboBox()
        self.state_combo.addItems(["open", "lockdown"])
        row_state.addWidget(self.state_combo)
        layout.addLayout(row_state)

        row_target = QHBoxLayout()
        row_target.addWidget(QLabel("Target Scope:"))
        self.target_combo = QComboBox()
        self.target_combo.addItems(["matrix_websocket", "perimeter marked agents"])

        # attach values
        self.target_combo.setItemData(0, "matrix_websocket.toggle_perimeter")  # visible "matrix_websocket"
        self.target_combo.setItemData(1, "hive.toggle_perimeter")  # visible "all perimeter" -> "hive"
        row_target.addWidget(self.target_combo)
        layout.addLayout(row_target)

        # LOCKDOWN TIME
        row_time = QHBoxLayout()
        row_time.addWidget(QLabel("Lockdown Time (sec):"))
        self.time_input = QLineEdit()
        self.time_input.setPlaceholderText("0 = indefinite")
        row_time.addWidget(self.time_input)
        layout.addLayout(row_time)
    
        # BUTTON BAR
        btns = QHBoxLayout()

        send_btn = QPushButton("🚨 Apply Perimeter Change")
        send_btn.clicked.connect(self._send_toggle)
        btns.addWidget(send_btn)

        refresh_btn = QPushButton("Refresh Status")
        refresh_btn.clicked.connect(self._refresh_status)
        btns.addWidget(refresh_btn)

        layout.addLayout(btns)

        # OUTPUT TERMINAL
        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        layout.addWidget(QLabel("Agent Response:"))
        layout.addWidget(self.output_box)

        return layout

    # ----------------------------------------------------------
    def _send_toggle(self):
        try:
            lockdown_state = 0 if self.state_combo.currentText().lower() == "open" else 1
            lockdown_time = int(self.time_input.text() or 0)
            #token = self.token_input.text().strip()

            # Safety confirmation for indefinite lockdown
            if lockdown_state and lockdown_time == 0:
                confirm = QMessageBox.warning(
                    self,
                    "⚠️ Confirm Permanent Lockdown",
                    (
                        "You are setting the lockdown time to 0 (indefinite).\n\n"
                        "This will completely disable packet processing until reopened "
                        "through another transport such as matrix_https or matrix_email.\n\n"
                        "Are you absolutely sure you want to continue?"
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if confirm == QMessageBox.StandardButton.No:
                    self.output_box.append("🚫 Lockdown canceled by user.\n")
                    return

            pk = Packet()
            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": self.target_combo.itemData(self.target_combo.currentIndex()),
                    "payload": {
                        "lockdown_state": lockdown_state,
                        "lockdown_time": lockdown_time,
                        #"token": token,
                        "session_id": self.session_id,
                        "return_handler": "matrix_websocket_panel.perimeter_ack"
                    }
                }
            })

            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=pk,
            )

            self.output_box.append("📡 Sent perimeter toggle request...\n")

        except Exception as e:
            emit_gui_exception_log("MatrixWebsocketPanel._send_toggle", e)

    # ----------------------------------------------------------
    def _refresh_status(self):
        try:
            pk = Packet()
            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": "matrix_https.status",
                    "payload": {
                        "session_id": self.session_id,
                        "return_handler": "matrix_websocket_panel.status_ack",
                    }
                }
            })

            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=pk,
            )
            self.output_box.append("📡 Requesting perimeter status...\n")

        except Exception as e:
            emit_gui_exception_log("MatrixWebsocketPanel._refresh_status", e)

    # ----------------------------------------------------------
    def _perimeter_ack(self, session_id, channel, source, payload, **_):
        """Callback for toggle results"""
        if session_id != self.session_id:
            return
        formatted = json.dumps(payload, indent=2)
        QMetaObject.invokeMethod(
            self.output_box,
            "setPlainText",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, f"🌐 Perimeter Toggle ACK:\n{formatted}")
        )

    # ----------------------------------------------------------
    def _status_ack(self, session_id, channel, source, payload, **_):
        """Callback for perimeter.status"""
        if session_id != self.session_id:
            return
        formatted = json.dumps(payload, indent=2)
        QMetaObject.invokeMethod(
            self.output_box,
            "setPlainText",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, f"📊 Perimeter Status:\n{formatted}")
        )

    # ----------------------------------------------------------
    def _connect_signals(self):
        super()._connect_signals() if hasattr(super(), "_connect_signals") else None
        self.bus.on("inbound.verified.matrix_websocket_panel.perimeter_ack", self._perimeter_ack)
        self.bus.on("inbound.verified.matrix_websocket_panel.status_ack", self._status_ack)

    def _disconnect_signals(self):
        super()._disconnect_signals() if hasattr(super(), "_disconnect_signals") else None
        self.bus.off("inbound.verified.matrix_websocket_panel.perimeter_ack", self._perimeter_ack)
        self.bus.off("inbound.verified.matrix_websocket_panel.status_ack", self._status_ack)

    def get_panel_buttons(self):
        return [
            PanelButton("🌐", "Matrix Websocket", lambda: self.session_window.show_specialty_panel(self))
        ]
