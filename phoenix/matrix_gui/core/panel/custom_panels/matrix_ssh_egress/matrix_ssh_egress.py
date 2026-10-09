"""Phoenix perimeter controls for the Matrix SSH reply transport."""

import json
import time

from PyQt6.QtCore import Q_ARG, QMetaObject, Qt
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSpinBox, QTextEdit, QVBoxLayout,
)

from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface


class MatrixSshEgress(PhoenixPanelInterface):
    cache_panel = True

    def __init__(self, session_id, bus, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self._signals_connected = False
        self.setLayout(self._build_ui())

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel("📤 Matrix SSH Egress — Perimeter Control"))
        note = QLabel(
            "Lockdown pauses SSH replies, alerts and session controls. "
            "The SSH server and the separate Matrix SSH command ingress remain available. "
            "An acknowledgment may not arrive through a locked reply transport. "
            "Reopen it through the command transport, then Refresh Status to verify."
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
        self.target_combo.addItem("SSH egress agents", "matrix_ssh_egress.toggle_perimeter")
        self.target_combo.addItem("Perimeter marked agents", "hive.toggle_perimeter")
        self.target_combo.setToolTip(
            "SSH egress scope reaches all agents advertising matrix_ssh_egress.toggle_perimeter. "
            "Perimeter marked agents reaches all agents advertising hive.toggle_perimeter."
        )
        target_row.addWidget(self.target_combo)
        layout.addLayout(target_row)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Lockdown Time (sec):"))
        self.time_input = QSpinBox()
        self.time_input.setRange(0, 86400)
        self.time_input.setSpecialValueText("0 — indefinite")
        self.time_input.setValue(60)
        time_row.addWidget(self.time_input)
        layout.addLayout(time_row)

        buttons = QHBoxLayout()
        self.send_btn = QPushButton("Apply Perimeter Change")
        self.send_btn.clicked.connect(self._send_toggle)
        self.refresh_btn = QPushButton("Refresh Status")
        self.refresh_btn.clicked.connect(self._refresh_status)
        buttons.addWidget(self.send_btn)
        buttons.addWidget(self.refresh_btn)
        layout.addLayout(buttons)

        layout.addWidget(QLabel("Verified Agent Response:"))
        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setAcceptRichText(False)
        self.output_box.setPlainText("Use Refresh Status to request the live SSH egress state.")
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
            lockdown_time = self.time_input.value() if lockdown_state else 0
            if lockdown_state and lockdown_time == 0:
                confirmed = QMessageBox.warning(
                    self, "Confirm Indefinite SSH Egress Lockdown",
                    "SSH egress will stop sending replies until reopened.\n\n"
                    "Use a working command transport to reopen it. An acknowledgment "
                    "may be unavailable while the reply transport is locked.\n\n"
                    "The perimeter-wide scope can also lock command transports, "
                    "requiring another working route or server-side recovery.\n\nContinue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if confirmed != QMessageBox.StandardButton.Yes:
                    self.output_box.setPlainText("Lockdown canceled; no request sent.")
                    return

            self._send_request(
                self.target_combo.currentData(), "matrix_ssh_egress_panel.perimeter_ack",
                lockdown_state=lockdown_state, lockdown_time=lockdown_time,
            )
            message = "Sent SSH egress perimeter change; awaiting agent acknowledgment."
            if lockdown_state:
                message += (
                    "\nAn acknowledgment may be unavailable during lockdown. "
                    "Reopen or wait for the timer, then Refresh Status to verify the state."
                )
            self.output_box.setPlainText(message)
        except Exception as error:
            emit_gui_exception_log("MatrixSshEgress._send_toggle", error)
            self.output_box.setPlainText("Could not send the SSH egress perimeter request.")

    def _refresh_status(self):
        try:
            self._send_request("matrix_ssh_egress.status", "matrix_ssh_egress_panel.status_ack")
            self.output_box.setPlainText(
                "Requesting live SSH egress status; awaiting a verified response.\n"
                "Replies require an open incoming transport."
            )
        except Exception as error:
            emit_gui_exception_log("MatrixSshEgress._refresh_status", error)
            self.output_box.setPlainText("Could not request SSH egress status.")

    def _show_response(self, session_id, heading, payload):
        if session_id != self.session_id or not isinstance(payload, dict):
            return
        # Callback dispatch may run outside Qt's GUI thread. Render as plain
        # text so agent-supplied strings cannot become HTML in the panel.
        QMetaObject.invokeMethod(
            self.output_box, "setPlainText", Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, f"{heading}:\n{json.dumps(payload, indent=2)}"),
        )

    def _perimeter_ack(self, session_id, channel=None, source=None, payload=None, **_):
        self._show_response(session_id, "SSH Egress Perimeter ACK", payload)

    def _status_ack(self, session_id, channel=None, source=None, payload=None, **_):
        self._show_response(session_id, "SSH Egress Status", payload)

    def _connect_signals(self):
        if self._signals_connected:
            return
        self.bus.on("inbound.verified.matrix_ssh_egress_panel.perimeter_ack", self._perimeter_ack)
        self.bus.on("inbound.verified.matrix_ssh_egress_panel.status_ack", self._status_ack)
        self._signals_connected = True

    def _disconnect_signals(self):
        if not self._signals_connected:
            return
        self.bus.off("inbound.verified.matrix_ssh_egress_panel.perimeter_ack", self._perimeter_ack)
        self.bus.off("inbound.verified.matrix_ssh_egress_panel.status_ack", self._status_ack)
        self._signals_connected = False

    def get_panel_buttons(self):
        return [PanelButton(
            "📤", "Matrix SSH Egress",
            lambda: self.session_window.show_specialty_panel(self),
        )]
