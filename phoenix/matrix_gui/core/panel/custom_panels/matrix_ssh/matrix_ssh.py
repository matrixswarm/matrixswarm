"""Phoenix perimeter controls for the durable Matrix SSH ingress."""

import json
import time

from PyQt6.QtCore import Q_ARG, QMetaObject, Qt
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTextEdit, QVBoxLayout,
)

from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface


class MatrixSsh(PhoenixPanelInterface):
    cache_panel = True

    def __init__(self, session_id, bus, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self._signals_connected = False
        self.setLayout(self._build_ui())

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel("🛡️ Matrix SSH — Perimeter Control"))
        note = QLabel(
            "Lockdown pauses Matrix SSH inbox processing, not the SSH server. "
            "Packets remain queued. Use a timer or keep another command transport "
            "open to restore intake; SSH-delivered status requests also wait while locked."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        state_row = QHBoxLayout()
        state_row.addWidget(QLabel("Perimeter State:"))
        self.state_combo = QComboBox()
        self.state_combo.addItems(["open", "lockdown"])
        state_row.addWidget(self.state_combo)
        layout.addLayout(state_row)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target Scope:"))
        self.target_combo = QComboBox()
        self.target_combo.addItem("matrix_ssh", "matrix_ssh.toggle_perimeter")
        self.target_combo.addItem("perimeter marked agents", "hive.toggle_perimeter")
        target_row.addWidget(self.target_combo)
        layout.addLayout(target_row)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Lockdown Time (sec):"))
        self.time_input = QLineEdit()
        self.time_input.setPlaceholderText("0 = indefinite")
        time_row.addWidget(self.time_input)
        layout.addLayout(time_row)

        buttons = QHBoxLayout()
        self.send_btn = QPushButton("🚨 Apply Perimeter Change")
        self.send_btn.clicked.connect(self._send_toggle)
        self.refresh_btn = QPushButton("Refresh Status")
        self.refresh_btn.clicked.connect(self._refresh_status)
        buttons.addWidget(self.send_btn)
        buttons.addWidget(self.refresh_btn)
        layout.addLayout(buttons)

        layout.addWidget(QLabel("Agent Response:"))
        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        layout.addWidget(self.output_box)
        return layout

    def _send_request(self, service, return_handler, **payload):
        packet = Packet()
        packet.set_data({
            "handler": "cmd_service_request",
            "ts": time.time(),
            "content": {
                "service": service,
                "payload": {
                    **payload,
                    "session_id": self.session_id,
                    "return_handler": return_handler,
                },
            },
        })
        self.bus.emit(
            "outbound.message", session_id=self.session_id,
            channel="outgoing.command", packet=packet,
        )

    def _send_toggle(self):
        try:
            lockdown_state = int(self.state_combo.currentText() == "lockdown")
            lockdown_time = int(self.time_input.text().strip() or "0")
            if lockdown_time < 0:
                raise ValueError("Lockdown time cannot be negative.")

            if lockdown_state and lockdown_time == 0:
                confirmed = QMessageBox.warning(
                    self, "Confirm Indefinite SSH Perimeter Lockdown",
                    "A time of 0 pauses inbox processing indefinitely.\n\n"
                    "Commands sent through matrix_ssh cannot reopen it while locked. "
                    "You will need another working command transport, such as "
                    "matrix_https or matrix_email, or server-side recovery.\n\n"
                    "The hive-wide scope can also lock other perimeter transports. "
                    "The SSH server itself is not disabled.\n\nContinue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if confirmed != QMessageBox.StandardButton.Yes:
                    self.output_box.append("Lockdown canceled; no request sent.")
                    return

            self._send_request(
                self.target_combo.currentData(), "matrix_ssh_panel.perimeter_ack",
                lockdown_state=lockdown_state, lockdown_time=lockdown_time,
            )
            self.output_box.append("Sent SSH perimeter change; awaiting agent acknowledgment.")
        except ValueError as error:
            self.output_box.append(f"Invalid lockdown time: {error}")
        except Exception as error:
            emit_gui_exception_log("MatrixSsh._send_toggle", error)
            self.output_box.append("Could not send the SSH perimeter request.")

    def _refresh_status(self):
        try:
            self._send_request("matrix_ssh.status", "matrix_ssh_panel.status_ack")
            self.output_box.append("Requesting SSH perimeter status; awaiting agent response.")
        except Exception as error:
            emit_gui_exception_log("MatrixSsh._refresh_status", error)
            self.output_box.append("Could not request SSH perimeter status.")

    def _show_response(self, session_id, heading, payload):
        if session_id != self.session_id:
            return
        # Verified bus callbacks may run outside Qt's GUI thread.
        QMetaObject.invokeMethod(
            self.output_box, "setPlainText", Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, f"{heading}:\n{json.dumps(payload, indent=2)}"),
        )

    def _perimeter_ack(self, session_id, channel=None, source=None, payload=None, **_):
        self._show_response(session_id, "SSH Perimeter Toggle ACK", payload)

    def _status_ack(self, session_id, channel=None, source=None, payload=None, **_):
        self._show_response(session_id, "SSH Perimeter Status", payload)

    def _connect_signals(self):
        if self._signals_connected:
            return
        self.bus.on("inbound.verified.matrix_ssh_panel.perimeter_ack", self._perimeter_ack)
        self.bus.on("inbound.verified.matrix_ssh_panel.status_ack", self._status_ack)
        self._signals_connected = True

    def _disconnect_signals(self):
        if not self._signals_connected:
            return
        self.bus.off("inbound.verified.matrix_ssh_panel.perimeter_ack", self._perimeter_ack)
        self.bus.off("inbound.verified.matrix_ssh_panel.status_ack", self._status_ack)
        self._signals_connected = False

    def get_panel_buttons(self):
        return [PanelButton(
            "🛡️", "Matrix SSH",
            lambda: self.session_window.show_specialty_panel(self),
        )]
