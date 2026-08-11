# Commander & ChatGPT — Victory Always Edition
# MULTIPLEXER PANEL — Switch transport channels
from PyQt6.QtWidgets import (
    QVBoxLayout, QLabel, QComboBox, QGroupBox,
    QPushButton, QDialog, QHBoxLayout
)
from PyQt6.QtCore import Qt
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log


class MultiplexerPanel(QDialog):
    """
    Transport Multiplexer UI Panel.

    Provides a graphical interface to view and switch transport channels for a session.
    It manages two types of transports:
      • Incoming (payload.reception): Informational only.
      • Outgoing (outgoing.command): Can be switched live to change the outbound command route.

    Attributes:
        session_id (str): The unique identifier for the session.
        bus (object): The message bus instance.
        node (object): The node instance.
        session_window (QMainWindow): The main session window reference.
        deployment (dict): The deployment configuration containing agent information.
        incoming_dropdown (QComboBox): Dropdown for incoming transport selection.
        outgoing_dropdown (QComboBox): Dropdown for outgoing transport selection.
    """

    def __init__(self, session_id, bus, node, session_window):
        """
        Initialize the MultiplexerPanel.

        Args:
            session_id (str): The ID of the current session.
            bus (object): The communication bus.
            node (object): The local node instance.
            session_window (QMainWindow): Reference to the parent session window.
        """
        super().__init__(session_window)
        try:
            self.session_id = session_id
            self.bus = bus
            self.node = node
            self.session_window = session_window
            self.deployment = session_window.deployment

            self.setWindowTitle("Multiplexer")
            self.setMinimumSize(460, 240)
            self.setModal(False)

            layout = QVBoxLayout(self)
            layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            layout.setSpacing(10)

            title = QLabel("⚡ Transport Multiplexer")
            title.setStyleSheet("font-size: 18px; font-weight: bold;")
            layout.addWidget(title)

            incoming_agents = []
            outgoing_agents = []

            for a in self.deployment.get("agents", []):
                conn = a.get("connection", {}) or {}
                channel = (conn.get("channel") or "").strip().lower()
                uid = a.get("universal_id", "")
                name = a.get("name", uid)
                proto = conn.get("proto", "")

                print("[MUX][AGENT]", name, uid, proto, channel)

                if channel == "payload.reception":
                    incoming_agents.append(a)

                elif channel == "outgoing.command":
                    outgoing_agents.append(a)

            # ------------------------------
            # Incoming Transport
            # ------------------------------
            incoming_group = QGroupBox("Incoming Transport (payload.reception)")
            ig_layout = QVBoxLayout()
            incoming_group.setLayout(ig_layout)

            self.incoming_dropdown = QComboBox()

            for a in incoming_agents:
                uid = a.get("universal_id", "")
                name = a.get("name", uid)
                self.incoming_dropdown.addItem(f"{name} ({uid})", uid)

            # Prefer explicitly flagged default_payload_reception
            # Match deployment boot policy: first flagged default wins.
            preferred_incoming_index = 0
            found_default_payload = False

            for i, a in enumerate(incoming_agents):
                conn = a.get("connection", {}) or {}
                if bool(conn.get("default_payload_reception", False)):
                    preferred_incoming_index = i
                    found_default_payload = True
                    break

            # Fallback: prefer websocket if no explicit default set
            if not found_default_payload:
                for i, a in enumerate(incoming_agents):
                    conn = a.get("connection", {}) or {}
                    proto = (conn.get("proto") or "").strip().lower()
                    name = (a.get("name") or "").strip().lower()
                    if proto == "wss" or "websocket" in name:
                        preferred_incoming_index = i
                        break

            if self.incoming_dropdown.count() > 0:
                self.incoming_dropdown.setCurrentIndex(preferred_incoming_index)

            # Keep visible/inspectable, but informational only
            self.incoming_dropdown.setToolTip(
                "Select the active ingress transport for payload.reception. "
                "Applying will stop other ingress connectors and launch the selected one."
            )

            ig_layout.addWidget(self.incoming_dropdown)
            layout.addWidget(incoming_group)

            # ------------------------------
            # Outgoing Transport
            # ------------------------------
            outgoing_group = QGroupBox("Outgoing Transport (outgoing.command)")
            og_layout = QVBoxLayout()
            outgoing_group.setLayout(og_layout)

            self.outgoing_dropdown = QComboBox()
            for a in outgoing_agents:
                uid = a.get("universal_id", "")
                name = a.get("name", uid)
                self.outgoing_dropdown.addItem(f"{name} ({uid})", uid)

            og_layout.addWidget(self.outgoing_dropdown)
            layout.addWidget(outgoing_group)

            # ------------------------------
            # Bottom Action Row
            # ------------------------------
            btn_row = QHBoxLayout()

            apply_incoming_btn = QPushButton("Apply Incoming")
            apply_incoming_btn.setToolTip(
                "Switch only the payload.reception ingress connector."
            )
            apply_incoming_btn.clicked.connect(self._apply_incoming_route)
            btn_row.addWidget(apply_incoming_btn)

            apply_outgoing_btn = QPushButton("Apply Outgoing")
            apply_outgoing_btn.setToolTip(
                "Switch only the outgoing.command egress connector."
            )
            apply_outgoing_btn.clicked.connect(self._apply_outgoing_route)
            btn_row.addWidget(apply_outgoing_btn)

            close_btn = QPushButton("Close")
            close_btn.clicked.connect(self.close)
            btn_row.addWidget(close_btn)

            layout.addLayout(btn_row)

        except Exception as e:
            emit_gui_exception_log("MultiplexerPanel.__init__", e)

    # ----------------------------------------------------------
    # APPLY TRANSPORT SELECTIONS
    # ----------------------------------------------------------
    def _apply_outgoing_route(self):
        """Switch only the selected outgoing.command connector."""
        try:
            selected_out_uid = self.outgoing_dropdown.currentData()
            if not selected_out_uid:
                return

            outbound = self.session_window.outbound_dispatcher
            for a in self.deployment.get("agents", []):
                if a.get("universal_id") == selected_out_uid:
                    outbound.set_outbound_connector(a)
                    self.session_window.outgoing_badge.setText(f"Outgoing: {selected_out_uid}  ⚪")
                    self.session_window.status_label.setText(
                        f"Status: Outgoing command route set to {self.outgoing_dropdown.currentText().strip()}"
                    )
                    print(f"[MUX][OUTGOING] Switched egress to: {selected_out_uid}")
                    break
            else:
                print(f"[MUX][OUTGOING] Unknown outgoing connector: {selected_out_uid}")

        except Exception as e:
            emit_gui_exception_log("MultiplexerPanel._apply_outgoing_route", e)

    def _apply_incoming_route(self):
        """Switch only the selected payload.reception connector."""
        try:
            selected_in_uid = self.incoming_dropdown.currentData()
            if not selected_in_uid:
                return

            if selected_in_uid == getattr(self.session_window, "preferred_incoming_uid", None):
                self.session_window.status_label.setText(
                    f"Status: Incoming route already set to {self.incoming_dropdown.currentText().strip()}"
                )
                return

            if self.session_window.switch_inbound_connector(selected_in_uid):
                self.session_window.status_label.setText(
                    f"Status: Incoming payload route set to {self.incoming_dropdown.currentText().strip()}"
                )
                print(f"[MUX][INCOMING] Switched ingress to: {selected_in_uid}")

        except Exception as e:
            emit_gui_exception_log("MultiplexerPanel._apply_incoming_route", e)

    def sync_with_current_connector(self):
        """
        Sync dropdown selections to match live session state.

        This method is UI-only:
          - does NOT launch/stop connectors
          - does NOT modify dispatcher state
          - only updates dropdown selection to reflect current reality
        """
        try:
            # --------------------------
            # Sync outgoing dropdown
            # --------------------------
            outbound = getattr(self.session_window, "outbound_dispatcher", None)
            if outbound:
                agent = outbound.get_outbound_connection()
                if agent and isinstance(agent, dict):
                    current_out_uid = agent.get("universal_id", "")
                    matched = False

                    for i in range(self.outgoing_dropdown.count()):
                        item_uid = self.outgoing_dropdown.itemData(i)
                        if item_uid == current_out_uid:
                            self.outgoing_dropdown.setCurrentIndex(i)
                            matched = True
                            break

                    if not matched:
                        print(f"[MULTIPLEXER][SYNC] No outgoing dropdown match for uid={current_out_uid}")
                    else:
                        print(f"[MULTIPLEXER][SYNC] Outgoing dropdown synced → {self.outgoing_dropdown.currentText()}")

            # --------------------------
            # Sync incoming dropdown
            # --------------------------
            current_in_uid = getattr(self.session_window, "preferred_incoming_uid", None)

            # optional fallback to dispatcher if session state not set
            if not current_in_uid:
                inbound = getattr(self.session_window, "inbound_dispatcher", None)
                if inbound:
                    in_agent = inbound.get_inbound_connection()
                    if in_agent and isinstance(in_agent, dict):
                        current_in_uid = in_agent.get("universal_id", "")

            if current_in_uid:
                matched = False
                for i in range(self.incoming_dropdown.count()):
                    item_uid = self.incoming_dropdown.itemData(i)
                    if item_uid == current_in_uid:
                        self.incoming_dropdown.setCurrentIndex(i)
                        matched = True
                        break

                if not matched:
                    print(f"[MULTIPLEXER][SYNC] No incoming dropdown match for uid={current_in_uid}")
                else:
                    print(f"[MULTIPLEXER][SYNC] Incoming dropdown synced → {self.incoming_dropdown.currentText()}")

        except Exception as e:
            emit_gui_exception_log("MultiplexerPanel.sync_with_current_connector", e)