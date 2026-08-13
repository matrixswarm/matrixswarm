# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import time
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QEvent
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel,  QAbstractItemView, QTableWidgetItem,
    QPushButton, QMessageBox, QLineEdit, QWidget, QHBoxLayout,  QTableWidget

)
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.modules.vault.services.vault_connection_singleton import VaultConnectionSingleton
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log


class PasswordField(QWidget):
    """A QLineEdit that shows password only while focused."""

    def __init__(self, real_password: str):
        super().__init__()
        self.real_password = real_password or ""
        self.line = QLineEdit("********" if real_password else "")
        self.line.setEchoMode(QLineEdit.EchoMode.Normal)
        self.line.setReadOnly(True)
        self.line.installEventFilter(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.line)
        self.setLayout(layout)

    def eventFilter(self, obj, event):
        try:
            if obj == self.line:
                if event.type() == QEvent.Type.FocusIn:
                    # Show the actual password
                    self.line.setText(self.real_password)
                elif event.type() == QEvent.Type.FocusOut:
                    # Mask again when focus lost
                    self.line.setText("********" if self.real_password else "")
            return super().eventFilter(obj, event)
        except Exception as e:
            emit_gui_exception_log("PasswordField.eventFilter", e)

class ManageServersDialog(QDialog):
    populateRequested = pyqtSignal(dict)

    def __init__(self, session_id, bus, parent=None):
        super().__init__(parent)

        try:
            self.setWindowTitle("📡 Manage Email Servers")
            self.resize(640, 360)
            self.session_id = session_id
            self.bus = bus

            self._initialized = False
            self._dirty = False

            layout = QVBoxLayout(self)
            layout.addWidget(QLabel("Configured Email Accounts (from EmailCheck Agent):"))

            # === table ===
            self.table = QTableWidget(0, 6)
            self.table.setHorizontalHeaderLabels(
                ["Serial", "Host", "Port", "User", "Encryption", "Password"]
            )
            self.table.cellChanged.connect(self._on_cell_changed)
            layout.addWidget(self.table)

            # === buttons ===
            row = QHBoxLayout()
            self.refresh_btn = QPushButton("🔁 Refresh")
            self.refresh_btn.clicked.connect(self._refresh)
            self.push_btn = QPushButton("🚀 Push to Server")
            self.push_btn.clicked.connect(self._push_to_server)

            self.close_btn = QPushButton("Close")
            self.close_btn.clicked.connect(self._handle_close)

            #delete from table button
            self.del_btn = QPushButton("🗑 Delete Selected")
            self.del_btn.clicked.connect(self._delete_selected_row)
            row.addWidget(self.del_btn)

            row.addWidget(self.refresh_btn)
            row.addStretch()
            row.addWidget(self.push_btn)
            row.addWidget(self.close_btn)
            layout.addLayout(row)

            # === Vault connections ===
            vault_label = QLabel("📥 Available Vault Email Connections")
            layout.addWidget(vault_label)
            self.vault_table = QTableWidget(0, 6)
            self.vault_table.setHorizontalHeaderLabels(
                ["Label", "User", "Host", "Port", "Encryption", ""]
            )
            layout.addWidget(self.vault_table)
            self._load_vault_email_accouns()

            # === connect signal ===
            self.populateRequested.connect(self._populate_safe)

            # === auto-load ===
            self._refresh()
        except Exception as e:
            emit_gui_exception_log("ManageServersDialog.__init__", e)

    # -------------------------------------------------------------------------
    def _refresh(self):
        """Ask agent to list configured email accounts."""
        try:
            payload = {
                "session_id": self.session_id,
                "return_handler": "check_mail.manage_servers_dialog.list_accounts",
            }
            pk = Packet()
            pk.set_data(
                {
                    "handler": "cmd_service_request",
                    "ts": time.time(),
                    "content": {
                        "service": "hive.email_check.list_accounts",
                        "payload": payload,
                    },
                }
            )
            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=pk,
            )
            self._await_response()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to request account list:\n{e}")

    def _await_response(self):
        """Subscribe for the response and refresh the table."""
        try:
            scoped = f"inbound.verified.check_mail.manage_servers_dialog.list_accounts"

            def handler(session_id, channel, source, payload, **_):
                try:
                    content = payload.get("content", {})
                    accounts = content.get("accounts", {})
                    self.populateRequested.emit(accounts)
                except Exception as e:
                    print(f"[MANAGE-SERVERS][ERROR] {e}")
                finally:
                    self.bus.off(scoped, handler)

            self.bus.on(scoped, handler)
        except Exception as e:
            emit_gui_exception_log("ManageServersDialog._await_response", e)

    def make_readonly_item(self, text):
        try:
            item = QTableWidgetItem(str(text))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return item
        except Exception as e:
            emit_gui_exception_log("ManageServersDialog.make_readonly_item", e)

    # -------------------------------------------------------------------------
    @pyqtSlot(dict)
    def _populate_safe(self, accounts: dict):

        try:
            self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

            """Thread-safe GUI update."""
            self.table.blockSignals(True)
            self.table.setRowCount(0)
            for i, (serial, data) in enumerate(accounts.items()):
                self.table.insertRow(i)
                self.table.setItem(i, 0, self.make_readonly_item(serial))
                self.table.setItem(i, 1, self.make_readonly_item(str(data.get("incoming_server", ""))))
                self.table.setItem(i, 2, self.make_readonly_item(str(data.get("incoming_port", ""))))
                self.table.setItem(i, 3, self.make_readonly_item(str(data.get("incoming_username", ""))))
                self.table.setItem(i, 4, self.make_readonly_item(str(data.get("encryption", ""))))

                real_pw = data.get("incoming_password", "")
                pw_widget = PasswordField(real_pw)
                self.table.setCellWidget(i, 5, pw_widget)

            self.table.resizeColumnsToContents()
            self._initialized = True
            self._dirty = False
            self.table.blockSignals(False)

            self.bus.emit(
                "inbound.verified.check_mail.load_email_accounts",
                payload={"content": {"accounts": accounts}},
            )

        except Exception as e:
            emit_gui_exception_log("ManageServersDialog._populate_safe", e)

    # -------------------------------------------------------------------------
    def _on_cell_changed(self, row, col):
        if not self._initialized:
            return
        self._dirty = True

    def _collect_table_data(self) -> dict:
        """Convert table back into the dict expected by the agent."""

        try:
            out = {}
            seen_serials = set()
            for i in range(self.table.rowCount()):
                serial_item = self.table.item(i, 0)
                if not serial_item:
                    continue
                serial = serial_item.text().strip()
                if not serial:
                    QMessageBox.warning(self, "Missing Serial", f"Row {i + 1} missing serial.")
                    continue
                if serial in seen_serials:
                    QMessageBox.warning(self, "Duplicate Serial", f"Serial '{serial}' appears more than once.")
                    return {}  # abort push
                seen_serials.add(serial)

                host = self.table.item(i, 1).text().strip()
                port = self.table.item(i, 2).text().strip()
                user = self.table.item(i, 3).text().strip()
                enc = self.table.item(i, 4).text().strip()
                pw_widget = self.table.cellWidget(i, 5)
                password = pw_widget.real_password if pw_widget else ""

                out[serial] = {
                    "incoming_server": host,
                    "incoming_port": port,
                    "incoming_username": user,
                    "incoming_password": password,
                    "incoming_encryption": enc,
                }
            return out
        except Exception as e:
            emit_gui_exception_log("ManageServersDialog._collect_table_data", e)

    def _delete_selected_row(self):
        """Delete the currently selected server from the table."""

        try:
            row = self.table.currentRow()
            if row < 0:
                QMessageBox.warning(self, "No Selection", "Select a row to delete.")
                return
            serial_item = self.table.item(row, 0)
            serial = serial_item.text() if serial_item else "unknown"
            confirm = QMessageBox.question(
                self,
                "Confirm Delete",
                f"Remove server '{serial}' from the list?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
            self.table.removeRow(row)
            self._dirty = True
        except Exception as e:
            emit_gui_exception_log("ManageServersDialog._delete_selected_row", e)

    # -------------------------------------------------------------------------
    def _push_to_server(self):
        """Send all table data in one swoop."""
        try:
            if not self._initialized:
                QMessageBox.warning(self, "Not Ready", "Server list not yet loaded.")
                return

            data = self._collect_table_data()
            content = {
                "service": "hive.email_check.update_accounts",
                "payload": {
                    "data": data,
                    "session_id": self.session_id,
                }
            }

            pk = Packet()
            pk.set_data(
                {
                    "handler": "cmd_service_request",
                    "ts": time.time(),
                    "content": content,
                }
            )
            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=pk,
            )

            self.bus.emit(
                "inbound.verified.check_mail.load_email_accounts",
                payload={"content": {"accounts": data}},
            )

            self._dirty = False
            QMessageBox.information(self, "Sent", "✅ Connections pushed to EmailCheck agent.")
        except Exception as e:
            emit_gui_exception_log("ManageServersDialog._push_to_server", e)

        # inside _push_to_server, after success:
        #self.parent().conn_selector.clear()
        #self.parent()._temp_load_email_connections()

    # -------------------------------------------------------------------------
    def _handle_close(self):
        """Warn if unsaved changes before closing."""
        try:
            if self._dirty:
                resp = QMessageBox.question(
                    self,
                    "Unsaved Changes",
                    "You have unsent changes. Push to server before closing?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel,
                )
                if resp == QMessageBox.StandardButton.Yes:
                    self._push_to_server()
                    self.accept()
                elif resp == QMessageBox.StandardButton.No:
                    self.accept()
                else:
                    return
            else:
                self.accept()

        except Exception as e:
            emit_gui_exception_log("ManageServersDialog._handle_close", e)

    def _load_vault_email_accouns(self):
        """List available incoming email connections from the vault directly."""
        try:

            vault = VaultConnectionSingleton.get()
            # Fetch registry data from cockpit over pipe
            vault_data = vault.fetch_fresh(target="registry") or {}
            email_conns = vault_data.get("imap", {})

            #d(email_section)
            self.vault_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.vault_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

            if not email_conns:
                print("[MANAGE-SERVERS] ⚠ No email section found in vault_data:", vault_data.keys())
                return

            print(f"[MANAGE-SERVERS] Loaded {len(email_conns)} email connection(s) from vault.")
            rows = email_conns.values()

            self.vault_table.setRowCount(len(rows))
            for i, cfg in enumerate(rows):

                if not isinstance(cfg, dict):
                    continue

                self.vault_table.insertRow(i)
                self.vault_table.setItem(i, 0, self.make_readonly_item(cfg.get("serial", "")))
                self.vault_table.setItem(i, 1, self.make_readonly_item(cfg.get("incoming_username", "")))
                self.vault_table.setItem(i, 2, self.make_readonly_item(cfg.get("incoming_server", "")))
                self.vault_table.setItem(i, 3, self.make_readonly_item(str(cfg.get("incoming_port", ""))))
                self.vault_table.setItem(i, 4, self.make_readonly_item(cfg.get("incoming_encryption", "")))

                # ➕ button to add this connection to the server table
                btn = QPushButton("➕ Add")
                btn.clicked.connect(lambda _, c=cfg: self._add_connection_to_table(c))
                self.vault_table.setCellWidget(i, 5, btn)
                self.vault_table.resizeColumnsToContents()

        except Exception as e:
            QMessageBox.warning(self, "Vault Load Error", f"Failed to load vault connections:\n{e}")

    def _add_connection_to_table(self, cfg):
        """Add a selected vault connection into the editable table."""
        try:
            serial = cfg.get("serial")
            if not serial:
                QMessageBox.warning(self, "Error", "Connection missing serial — cannot add.")
                return

            # Prevent duplicates
            for i in range(self.table.rowCount()):
                if self.table.item(i, 0) and self.table.item(i, 0).text().strip() == serial:
                    QMessageBox.information(self, "Duplicate", f"Connection '{serial}' is already in the table.")
                    return

            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(serial))
            self.table.setItem(row, 1, QTableWidgetItem(cfg.get("incoming_server", "")))
            self.table.setItem(row, 2, QTableWidgetItem(str(cfg.get("incoming_port", ""))))
            self.table.setItem(row, 3, QTableWidgetItem(cfg.get("incoming_username", "")))
            self.table.setItem(row, 4, QTableWidgetItem(cfg.get("incoming_encryption", "")))

            pw = cfg.get("incoming_password", "")
            self.table.setCellWidget(row, 5, PasswordField(pw))
            self._dirty = True

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to add connection:\n{e}")


