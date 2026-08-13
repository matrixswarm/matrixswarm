# Built by ChatGPT-5.1 + Commander 2025
import time
import json

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QTableWidget, QTableWidgetItem, QMessageBox, QTabWidget, QDialog, QHeaderView
)
from PyQt6.QtCore import QMetaObject, Q_ARG,pyqtSlot, Qt, QTimer
from enum import Enum

from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.event_bus import EventBus
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class MessageBoxType(Enum):
    INFORMATION = 0
    WARNING = 1

class TripwireLite(PhoenixPanelInterface):

    cache_panel = True  # keep panel cached like TrendIngest

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)

        self.status_data = ""
        self._signals_connected = False
        self._ui_ready = False

        # Connect signals first
        self._connect_signals()

        # Build UI first
        layout = self._build_layout()
        self.setLayout(layout)

        # Only then request data (safe)
        self._refresh_status()
        # Delay alert load until the event loop is idle
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(500, self._load_alerts)

        print("[TRIPWIRE_PANEL] Commander Edition panel online.")

    # --------------------------------------------------------------------
    # UI BUILD
    # --------------------------------------------------------------------
    def _build_layout(self):
        layout = QVBoxLayout()

        layout.addWidget(QLabel("<b>Tripwire Lite – Commander Edition</b>"))

        # Tabs
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # ======================================================
        # TAB 1: Controls
        # ======================================================
        dash = QWidget()
        dash_lay = QVBoxLayout()
        dash.setLayout(dash_lay)

        # --- Control Buttons ---
        row = QHBoxLayout()

        btn_refresh = QPushButton("Refresh Status")
        btn_refresh.clicked.connect(self._refresh_status)
        row.addWidget(btn_refresh)

        btn_enforce = QPushButton("Toggle Enforce")
        btn_enforce.clicked.connect(self._toggle_enforce)
        row.addWidget(btn_enforce)

        btn_dryrun = QPushButton("Toggle Dry-Run")
        btn_dryrun.clicked.connect(self._toggle_dryrun)
        row.addWidget(btn_dryrun)

        btn_reset = QPushButton("Reset Watches")
        btn_reset.clicked.connect(self._reset_watches)
        row.addWidget(btn_reset)

        dash_lay.addLayout(row)

        # --- Status Output ---
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        dash_lay.addWidget(self.status_text)

        self.tabs.addTab(dash, "Controls")

        # ======================================================
        # TAB 2: Alerts Table
        # ======================================================
        alerts_table_tab = QWidget()
        alerts_table_lay = QVBoxLayout()
        alerts_table_tab.setLayout(alerts_table_lay)

        self.alert_table = QTableWidget(0, 5)
        header = self.alert_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.alert_table.setHorizontalHeaderLabels(
            ["Time", "Path", "Status", "Inspect", "Restore"]
        )
        alerts_table_lay.addWidget(self.alert_table)

        btn_row = QHBoxLayout()
        btn_refresh = QPushButton("Refresh List")
        btn_refresh.clicked.connect(self._list_alerts)
        btn_row.addWidget(btn_refresh)

        btn_restore_all = QPushButton("Restore ALL")
        btn_restore_all.clicked.connect(self._restore_all)
        btn_row.addWidget(btn_restore_all)

        alerts_table_lay.addLayout(btn_row)

        self.tabs.addTab(alerts_table_tab, "Alerts")

        return layout

    def _load_alerts(self):
        self._send_service_request(
            "tripwire.guard.list_alerts",
            {
                "return_handler": "tripwire_panel.alerts_rx",
                "session_id": self.session_id,
            }
        )

    def _alerts_rx(self, session_id, channel, source, payload, **_):

        try:
            if session_id != self.session_id:
                return

            data = payload.get("content", payload)
            alerts = data.get("alerts", [])
            self.alert_table.setRowCount(0)

            seen = {}
            for a in alerts:
                key = a['path']
                # Always overwrite, so the latest state wins
                seen[key] = a

            # Now only loop through unique entries
            for a in seen.values():
                row = self.alert_table.rowCount()
                self.alert_table.insertRow(row)

                ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(a['ts']))
                self.alert_table.setItem(row, 0, QTableWidgetItem(ts))
                self.alert_table.setItem(row, 1, QTableWidgetItem(a['path']))
                self.alert_table.setItem(row, 2, QTableWidgetItem(a['status']))
                self.alert_table.setRowHeight(row, 42)
                QMetaObject.invokeMethod(
                    self,
                    "_add_alert_buttons",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(dict, a),
                    Q_ARG(int, row)
                )

        except Exception as e:
            emit_gui_exception_log("TripwirePanel._alerts_rx", e)

    @pyqtSlot(dict, int)
    def _add_alert_buttons(self, alert, row):

        # Inspect button
        btn_ins = QPushButton("Inspect")
        btn_ins.clicked.connect(lambda _, x=alert: self._inspect_alert(x))
        self.alert_table.setCellWidget(row, 3, btn_ins)

        status = alert.get("status", "")

        # If quarantined → show Restore
        if alert.get("status") == "restored":
            btn_del = QPushButton("Delete")
            btn_del.setStyleSheet("color: red;")
            btn_del.clicked.connect(lambda _, x=alert, r=row: self._delete_alert(x, r))
            self.alert_table.setCellWidget(row, 4, btn_del)
        else:
            btn_res = QPushButton("Restore")
            btn_res.clicked.connect(lambda _, x=alert: self._restore_item(x))
            self.alert_table.setCellWidget(row, 4, btn_res)

    def _delete_alert_row(self, alert):
        try:
            # Loop through the table and find the row with matching path
            for row in range(self.alert_table.rowCount()):
                path_item = self.alert_table.item(row, 1)  # Column 1 is Path
                if path_item and path_item.text() == alert.get("path"):
                    self.alert_table.removeRow(row)
                    break  # Stop once deleted
        except Exception as e:
            emit_gui_exception_log("TripwirePanel._delete_alert_row", e)

    def _delete_alert(self, alert, row):
        # Store the row index so we can use it in _delete_ack
        self._pending_delete_row = row
        self._send_service_request(
            "tripwire.guard.delete_alert",
            {
                "session_id": self.session_id,
                "return_handler": "tripwire_panel.delete_ack",
                "alert_id": alert.get("id"),
            }
        )

    def _delete_ack(self, session_id, channel, source, payload, **_):
        try:
            if session_id != self.session_id:
                return

            content = payload.get("content", payload)

            status = content.get("success", False)
            alert_id = content.get("alert_id", "?")

            msg = (
                f"🗑 Delete Ack\n"
                f"Alert ID: {alert_id}\n"
                f"Status: {'SUCCESS' if status else 'FAILED'}"
            )

            QTimer.singleShot(0, lambda: QMessageBox.information(self, "Delete", msg))

            # refresh the alerts table safely
            QTimer.singleShot(0, self._refresh_all_alert_tables)

        except Exception as e:
            emit_gui_exception_log("TripwirePanel._delete_ack", e)

    def _safe_popup( self, title: str, msg: str,  qbox_type: MessageBoxType = MessageBoxType.INFORMATION):
        try:
            if qbox_type == MessageBoxType.WARNING:
                QMessageBox.warning(self, title, msg)
            else:
                QMessageBox.information(self, title, msg)
        except Exception as e:
            emit_gui_exception_log("TripwirePanel._safe_popup", e)

    def _restore_item(self, alert):
        self._send_service_request(
            "tripwire.guard.restore_item",
            {
                "session_id": self.session_id,
                "return_handler": "tripwire_panel.restore_ack",
                "original_path": alert.get("path"),
                "qpath": alert.get("quarantine_path")
            }
        )

    def _restore_all(self):
        self._send_service_request(
            "tripwire.guard.restore_all",
            {
                "session_id": self.session_id,
                "return_handler": "tripwire_panel.restore_all_ack",
            }
        )

    def _inspect_alert(self, alert):

        try:
            dlg = QDialog(self)
            dlg.setWindowTitle("Inspect Quarantined File")

            layout = QVBoxLayout(dlg)
            layout.addWidget(QLabel(f"Original Path:\n{alert['path']}"))
            layout.addWidget(QLabel(f"Quarantined Path:\n{alert['quarantine_path']}"))

            # Show file contents (safe preview)
            try:
                with open(alert["quarantine_path"], "r", errors="ignore") as f:
                    txt = QTextEdit()
                    txt.setPlainText(f.read())
                    txt.setReadOnly(True)
                    layout.addWidget(txt)
            except:
                layout.addWidget(QLabel("(Binary or unreadable file)"))

            close = QPushButton("Close")
            close.clicked.connect(dlg.accept)
            layout.addWidget(close)

            dlg.exec()
        except Exception as e:
            emit_gui_exception_log("TripwirePanel._inspect_alert", e)

    def _restore_ack(self, session_id, channel, source, payload, **_):
        try:
            if session_id != self.session_id:
                return
            content = payload.get("content", payload)
            success = content.get("success", False)
            msg = "✅ File restored successfully!" if success else "❌ Restore failed."
            QTimer.singleShot(0, lambda: QMessageBox.information(self, "Restore", msg))
            QTimer.singleShot(0, self._refresh_all_alert_tables)
        except Exception as e:
            emit_gui_exception_log("TripwirePanel._restore_all_ack", e)

    def _restore_all_ack(self, session_id, channel, source, payload, **_):
        try:
            if session_id != self.session_id:
                return
            content = payload.get("content", payload)
            restored = content.get("restored", [])
            msg = f"Restored {len(restored)} items successfully."
            # Schedule the popup after control returns to Qt’s loop
            QTimer.singleShot(0, lambda: QMessageBox.information(self, "Restore All", msg))

            # Also delay _load_alerts so it doesn't run inside the same callback stack
            QTimer.singleShot(0, self._refresh_all_alert_tables)
        except Exception as e:
            emit_gui_exception_log("TripwirePanel._restore_all_ack", e)

    # --------------------------------------------------------------------
    # PANEL BUTTON
    # --------------------------------------------------------------------
    def get_panel_buttons(self):
        return [
            PanelButton("🛡️", "Tripwire Lite", lambda: self.session_window.show_specialty_panel(self))
        ]

    # --------------------------------------------------------------------
    # SERVICE REQUEST HELPERS
    # --------------------------------------------------------------------
    def _send_service_request(self, service, payload):
        """Universal proxy method for Tripwire service commands."""
        try:
            pk = Packet()
            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": service,
                    "payload": payload
                }
            })

            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=pk
            )
        except Exception as e:
            emit_gui_exception_log("TripwirePanel._send_service_request", e)
            QMessageBox.critical(self, "Tripwire Error", str(e))

    # --------------------------------------------------------------------
    # COMMAND: Refresh Status
    # --------------------------------------------------------------------
    def _refresh_status(self):
        self._send_service_request(
            "tripwire.guard.status",
            {
                "return_handler": "tripwire_panel.status_ack",
                "session_id": self.session_id
            }
        )
    # --------------------------------------------------------------------
    # COMMAND: Toggle Enforce
    # --------------------------------------------------------------------
    def _toggle_enforce(self):
        self._send_service_request(
            "tripwire.guard.toggle_enforce",
            {
                "return_handler": "tripwire_panel.enforce_ack",
                "session_id": self.session_id
            }
        )
    # --------------------------------------------------------------------
    # COMMAND: Toggle Dry-Run
    # --------------------------------------------------------------------
    def _toggle_dryrun(self):
        self._send_service_request(
            "tripwire.guard.toggle_dry_run",
            {
                "return_handler": "tripwire_panel.dryrun_ack",
                "session_id": self.session_id
            }
        )

    # --------------------------------------------------------------------
    # COMMAND: Reset Watch Loop
    # --------------------------------------------------------------------
    def _reset_watches(self):
        """Tell Tripwire agent to rebuild its inotify watch tree."""
        self._send_service_request(
            "tripwire.guard.tripwire_reset",  # real command name in the agent
            {
                "return_handler": "tripwire_panel.reset_ack",
                "session_id": self.session_id
            }
        )
    # --------------------------------------------------------------------
    # BUS HANDLERS
    # --------------------------------------------------------------------
    def _status_ack(self, session_id, channel, source, payload, **_):
        """Handles Tripwire status updates safely."""
        try:
            if session_id != self.session_id:
                return

            content = payload.get("content", payload)
            if not content:
                print("[_status_ack] empty payload")
                return

            formatted = json.dumps(content, indent=2)

            QMetaObject.invokeMethod(
                self,
                "_apply_status_update",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, formatted)
            )

        except Exception as e:
            emit_gui_exception_log("TripwirePanel._status_ack", e)

    @pyqtSlot(str)
    def _apply_status_update(self, formatted: str):
        """Executes in GUI thread — prevents Qt hang/focus bug."""
        try:
            self.status_data = json.loads(formatted)

            if getattr(self, "status_text", None):
                self.status_text.blockSignals(True)
                self.status_text.setPlainText(formatted)
                self.status_text.blockSignals(False)

        except Exception as e:
            emit_gui_exception_log("TripwirePanel._apply_status_update", e)

    def _enforce_ack(self, session_id, channel, source, payload, **_):
        """Thread-safe acknowledgment for Enforce toggle."""
        try:

            content = payload.get("content", payload)
            if not content:
                return

            if session_id != self.session_id:
                return

            enforce_state = bool(content.get("enforce", False))

            self.status_data = content
            formatted = json.dumps(content, indent=2)

            # -- GUI updates must be queued to main thread --
            if hasattr(self, "status_text"):
                QMetaObject.invokeMethod(
                    self.status_text,
                    "setPlainText",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, formatted)
                )


            # Show popup safely
            QMetaObject.invokeMethod(
                self,
                "_show_enforce_msg",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(bool, enforce_state)
            )

        except Exception as e:
            emit_gui_exception_log("TripwireLite._enforce_ack", e)

    @pyqtSlot(bool)
    def _show_enforce_msg(self, enforce_state):
        msg = f"🛡 Enforcement is now {'ENABLED' if enforce_state else 'DISABLED'}"
        if msg.strip():
            QMessageBox.information(self, "Enforce Mode", msg)

    def _dryrun_ack(self, session_id, channel, source, payload, **_):
        """Thread-safe acknowledgment for Dry-Run toggle."""
        try:
            content = payload.get("content", payload)
            if not content:
                return

            if session_id != self.session_id:
                return

            dry_run_state = bool(content.get("dry_run", False))

            self.status_data = content
            formatted = json.dumps(content, indent=2)

            # -- GUI updates must be queued to main thread --
            if hasattr(self, "status_text"):
                QMetaObject.invokeMethod(
                    self.status_text,
                    "setPlainText",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, formatted)
                )

            # GUI popup (safe)
            QMetaObject.invokeMethod(
                self,
                "_show_dryrun_msg",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(bool, dry_run_state)
            )

        except Exception as e:
            emit_gui_exception_log("TripwireLite._dryrun_ack", e)

    @pyqtSlot(bool)
    def _show_dryrun_msg(self, dry_run_state):

        msg = f"Dry-Run mode is now {'ENABLED' if dry_run_state else 'DISABLED'}"
        if msg.strip():  # guard ensures non-empty text
            QMessageBox.information(self, "Dry-Run Mode", msg)

    def _reset_ack(self, session_id, channel, source, payload, **_):
        """Confirmation callback after Tripwire rebuilds its watchers."""
        try:
            if session_id != self.session_id:
                return

            QMessageBox.information(
                self,
                "Tripwire",
                "✅ Tripwire watchers successfully reset.\nThe agent has rebuilt all inotify paths."
            )

            # optionally refresh status to verify it’s alive
            self._refresh_status()

        except Exception as e:
            emit_gui_exception_log("TripwireLite._reset_ack", e)

    def _list_alerts(self):
        """Request the list of quarantined files from Tripwire."""
        self._send_service_request(
            "tripwire.guard.list_alerts",
            {
                "return_handler": "tripwire_panel.alerts_rx",
                "session_id": self.session_id
            }
        )

    def _refresh_all_alert_tables(self):
        self._load_alerts()
        self._list_alerts()

    # --------------------------------------------------------------------
    # CONNECT SIGNALS
    # --------------------------------------------------------------------
    def on_deployment_updated(self, deployment):
        pass

    def _connect_signals(self):
        try:
            if not self._signals_connected:

                self.bus.on("inbound.verified.tripwire_panel.status_ack", self._status_ack)
                self.bus.on("inbound.verified.tripwire_panel.enforce_ack", self._enforce_ack)
                self.bus.on("inbound.verified.tripwire_panel.dryrun_ack", self._dryrun_ack)
                self.bus.on("inbound.verified.tripwire_panel.reset_ack", self._reset_ack)
                self.bus.on("inbound.verified.tripwire_panel.alerts_rx", self._alerts_rx)
                self.bus.on("inbound.verified.tripwire_panel.restore_ack", self._restore_ack)
                self.bus.on("inbound.verified.tripwire_panel.restore_all_ack", self._restore_all_ack)
                self.bus.on("inbound.verified.tripwire_panel.delete_ack", self._delete_ack)
                self._signals_connected = True

        except Exception as e:
            emit_gui_exception_log("CryptoAlert._connect_signals", e)

    def _disconnect_signals(self):
        pass

    def _on_close(self):

        try:
            if self._signals_connected:

                self.bus.off("inbound.verified.tripwire_panel.status_ack", self._status_ack)
                self.bus.off("inbound.verified.tripwire_panel.enforce_ack", self._enforce_ack)
                self.bus.off("inbound.verified.tripwire_panel.dryrun_ack", self._dryrun_ack)
                self.bus.off("inbound.verified.tripwire_panel.reset_ack", self._reset_ack)
                self.bus.off("inbound.verified.tripwire_panel.alerts_rx", self._alerts_rx)
                self.bus.off("inbound.verified.tripwire_panel.restore_ack", self._restore_ack)
                self.bus.off("inbound.verified.tripwire_panel.restore_all_ack", self._restore_all_ack)
                self.bus.off("inbound.verified.tripwire_panel.delete_ack", self._delete_ack)
                self._signals_connected = False

        except Exception as e:
            emit_gui_exception_log("CryptoAlert._disconnect_signals", e)