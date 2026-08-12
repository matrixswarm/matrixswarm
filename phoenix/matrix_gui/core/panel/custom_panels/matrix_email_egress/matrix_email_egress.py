# Authored by Daniel F MacDonald and ChatGPT aka The Generals
# Commander Edition - Matrix Email Egress Perimeter Panel
# Analog of the Matrix EMAIL EGRESS perimeter panel
import json
import time

from PyQt6.QtCore import QMetaObject, Q_ARG, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import (
    PhoenixPanelInterface,
)


class MatrixEmailEgress(PhoenixPanelInterface):
    cache_panel = True

    def __init__(self, session_id, bus, node=None, session_window=None):
        super().__init__(
            session_id,
            bus,
            node=node,
            session_window=session_window,
        )
        self.node = node
        self.setLayout(self._build_ui())

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel("🛰️ Matrix Email Egress - Perimeter Control"))

        row_state = QHBoxLayout()
        row_state.addWidget(QLabel("Perimeter State:"))
        self.state_combo = QComboBox()
        self.state_combo.addItems(["open", "lockdown"])
        row_state.addWidget(self.state_combo)
        layout.addLayout(row_state)

        row_target = QHBoxLayout()
        row_target.addWidget(QLabel("Target Scope:"))
        self.target_combo = QComboBox()
        self.target_combo.addItems(
            ["matrix_email_egress", "perimeter marked agents"]
        )
        self.target_combo.setItemData(
            0,
            "matrix_email_egress.toggle_perimeter",
        )
        self.target_combo.setItemData(1, "hive.toggle_perimeter")
        row_target.addWidget(self.target_combo)
        layout.addLayout(row_target)

        row_time = QHBoxLayout()
        row_time.addWidget(QLabel("Lockdown Time (sec):"))
        self.time_input = QLineEdit()
        self.time_input.setPlaceholderText("0 = indefinite")
        row_time.addWidget(self.time_input)
        layout.addLayout(row_time)

        buttons = QHBoxLayout()

        send_button = QPushButton("🚨 Apply Perimeter Change")
        send_button.clicked.connect(self._send_toggle)
        buttons.addWidget(send_button)

        refresh_button = QPushButton("Refresh Status")
        refresh_button.clicked.connect(self._refresh_status)
        buttons.addWidget(refresh_button)

        layout.addLayout(buttons)

        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        layout.addWidget(QLabel("Agent Response:"))
        layout.addWidget(self.output_box)

        return layout

    def _send_toggle(self):
        try:
            lockdown_state = (
                0 if self.state_combo.currentText().lower() == "open" else 1
            )
            lockdown_time = int(self.time_input.text() or 0)

            if lockdown_time < 0:
                raise ValueError("Lockdown time cannot be negative.")

            if lockdown_state and lockdown_time == 0:
                confirm = QMessageBox.warning(
                    self,
                    "⚠️ Confirm Permanent Lockdown",
                    (
                        "You are setting the lockdown time to 0 (indefinite).\n\n"
                        "This will disable email-egress packet processing until "
                        "it is reopened through another transport, such as "
                        "matrix_https or matrix_websocket.\n\n"
                        "Are you absolutely sure you want to continue?"
                    ),
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if confirm == QMessageBox.StandardButton.No:
                    self.output_box.append("🚫 Lockdown canceled by user.\n")
                    return

            packet = Packet()
            packet.set_data(
                {
                    "handler": "cmd_service_request",
                    "ts": time.time(),
                    "content": {
                        "service": self.target_combo.itemData(
                            self.target_combo.currentIndex()
                        ),
                        "payload": {
                            "lockdown_state": lockdown_state,
                            "lockdown_time": lockdown_time,
                            "session_id": self.session_id,
                            "return_handler": (
                                "matrix_email_egress_panel.perimeter_ack"
                            ),
                        },
                    },
                }
            )

            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=packet,
            )
            self.output_box.append("📡 Sent email-egress perimeter request...\n")

        except ValueError as error:
            self.output_box.append(f"❌ Invalid lockdown time: {error}\n")
        except Exception as error:
            emit_gui_exception_log(
                "MatrixEmailEgressPanel._send_toggle",
                error,
            )

    def _refresh_status(self):
        try:
            packet = Packet()
            packet.set_data(
                {
                    "handler": "cmd_service_request",
                    "ts": time.time(),
                    "content": {
                        "service": "matrix_email_egress.status",
                        "payload": {
                            "session_id": self.session_id,
                            "return_handler": (
                                "matrix_email_egress_panel.status_ack"
                            ),
                        },
                    },
                }
            )

            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=packet,
            )
            self.output_box.append("📡 Requesting email-egress status...\n")

        except Exception as error:
            emit_gui_exception_log(
                "MatrixEmailEgressPanel._refresh_status",
                error,
            )

    def _perimeter_ack(self, session_id, channel, source, payload, **_):
        if session_id != self.session_id:
            return

        formatted = json.dumps(payload, indent=2)
        QMetaObject.invokeMethod(
            self.output_box,
            "setPlainText",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, f"🛰️ Email Egress Perimeter ACK:\n{formatted}"),
        )

    def _status_ack(self, session_id, channel, source, payload, **_):
        if session_id != self.session_id:
            return

        formatted = json.dumps(payload, indent=2)
        QMetaObject.invokeMethod(
            self.output_box,
            "setPlainText",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, f"📊 Email Egress Status:\n{formatted}"),
        )

    def _connect_signals(self):
        if hasattr(super(), "_connect_signals"):
            super()._connect_signals()

        self.bus.on(
            "inbound.verified.matrix_email_egress_panel.perimeter_ack",
            self._perimeter_ack,
        )
        self.bus.on(
            "inbound.verified.matrix_email_egress_panel.status_ack",
            self._status_ack,
        )

    def _disconnect_signals(self):
        if hasattr(super(), "_disconnect_signals"):
            super()._disconnect_signals()

        self.bus.off(
            "inbound.verified.matrix_email_egress_panel.perimeter_ack",
            self._perimeter_ack,
        )
        self.bus.off(
            "inbound.verified.matrix_email_egress_panel.status_ack",
            self._status_ack,
        )

    def get_panel_buttons(self):
        return [
            PanelButton(
                "🛰️",
                "Matrix Email Egress",
                lambda: self.session_window.show_specialty_panel(self),
            )
        ]