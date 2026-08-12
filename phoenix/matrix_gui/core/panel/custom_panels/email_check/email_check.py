# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import time, re, html, json

from PyQt6.QtWidgets import QMessageBox, QInputDialog, QComboBox, QListWidget,  QGroupBox, QLabel, QVBoxLayout, QTextEdit, QHBoxLayout, QPushButton

from PyQt6.QtCore import QMetaObject, pyqtSlot,QTimer, Qt
from PyQt6.QtGui import QAction

from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.class_lib.email.email_display_parser import EmailDisplayParser

from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.vault.services.vault_connection_singleton import VaultConnectionSingleton
from .dialog.manage_servers_dialog import ManageServersDialog


class EmailCheck(PhoenixPanelInterface):
    cache_panel = True

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self.session_id = session_id
        self.node = node
        self.setLayout(self._build_layout())
        self._load_servers()
        self.bus=bus
        self.page_limit=20
        self._signals_connected=False

    # -------------------------------------------------------------------------
    # UI
    # -------------------------------------------------------------------------
    def _build_layout(self):

        try:
            # === Initialize ===
            layout = QVBoxLayout()
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(10)

            # === Connection selection ===
            layout.addWidget(QLabel("Select Email Account"))
            self.conn_selector = QComboBox()
            layout.addWidget(self.conn_selector)

            # === Hint ===
            self.manage_btn = QPushButton("⚙️ Load Servers - accounts are managed in the main cockpit (🌐 Connections).")
            self.manage_btn.clicked.connect(self._open_manage_dialog)
            self.manage_btn.setStyleSheet("color:#888; font-style:italic; margin-bottom:6px;")
            layout.addWidget(self.manage_btn)

            # === Account info ===
            info_group = QGroupBox("📡 Account Info")
            info_layout = QVBoxLayout()
            self.info_label = QLabel("No account selected.")
            self.info_label.setStyleSheet("color:#4ec9b0; font-family: monospace;")
            info_layout.addWidget(self.info_label)
            info_group.setLayout(info_layout)
            layout.addWidget(info_group)

            # === Mailbox section ===
            mailbox_group = QGroupBox("📬 Mailbox")
            mailbox_layout = QHBoxLayout()
            self.mail_list = QListWidget()
            self.mail_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
            self.mail_list.setMinimumWidth(320)
            self.mail_view = QTextEdit()
            self.mail_view.setReadOnly(True)
            self.mail_view.setPlaceholderText("Select a message to view its content…")
            mailbox_layout.addWidget(self.mail_list, 1)
            mailbox_layout.addWidget(self.mail_view, 2)
            mailbox_group.setLayout(mailbox_layout)
            layout.addWidget(mailbox_group)

            self._pending_body=None

            # === Bottom controls ===
            self.prev_btn = QPushButton("⬅️ Prev")
            self.next_btn = QPushButton("➡️ Next")
            self.check_btn = QPushButton("🔁 Check Now")
            self.check_btn.clicked.connect(self._check_now)
            self.popup_btn = QPushButton("🗖 View Full")
            self.popup_btn.clicked.connect(self._show_msg_full)
            self.prev_btn.clicked.connect(self._prev_page)
            self.next_btn.clicked.connect(self._next_page)

            # === Bottom controls (clean layout) ===
            nav = QHBoxLayout()

            # --- Left cluster ---
            nav.addWidget(self.check_btn)
            nav.addWidget(QLabel("★"))
            nav.addWidget(self.popup_btn)
            nav.addWidget(QLabel("★"))

            # --- Middle cluster ---
            self.select_all_btn = QPushButton("Select All")
            self.select_all_btn.clicked.connect(lambda: self.mail_list.selectAll())
            nav.addWidget(self.select_all_btn)

            self.del_btn = QPushButton("🗑 Delete")
            self.del_btn.clicked.connect(self._delete_selected)
            nav.addWidget(self.del_btn)
            nav.addWidget(QLabel("★"))

            # --- Right cluster ---
            nav.addWidget(self.prev_btn)
            nav.addWidget(self.next_btn)

            # --- Final spacing ---
            nav.addStretch()
            layout.addLayout(nav)

            #delect selected context menu
            self.mail_list.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
            delete_action = QAction("🗑 Delete Selected", self)
            delete_action.triggered.connect(self._delete_selected)
            self.mail_list.addAction(delete_action)

            #retrieve a message
            self.mail_list.itemDoubleClicked.connect(self._on_message_selected)

            # === Initialize ===
            self._temp_load_email_connections()
            return layout
        except Exception as e:
            emit_gui_exception_log("EmailCheck._build_layout", e)

    def _fmt_user_host(self, user: str, host: str) -> str:
        user = (user or "").strip()
        host = (host or "").strip()
        if not user:
            return f"(no-user)@{host}" if host else "(no-user)"
        return user if "@" in user else f"{user}@{host}"

    def _delete_selected(self):
        """Delete selected messages directly from the mailbox view."""
        try:
            selected = self.mail_list.selectedItems()
            if not selected:
                QMessageBox.warning(self, "No Selection", "Select one or more messages to delete.")
                return

            confirm = QMessageBox.question(
                self,
                "Confirm Delete",
                f"Delete {len(selected)} selected message(s)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

            serial = getattr(self, "_current_serial", None)
            if not serial:
                QMessageBox.warning(self, "No Active Account", "No mailbox loaded.")
                return

            delete_map = {}
            for item in selected:
                text = item.text()
                m = re.search(r"([0-9a-fA-F\-]{36})", text)
                if not m:
                    continue
                uuid_str = m.group(1)
                delete_map[uuid_str] = False  # local delete, remote=False

            if not delete_map:
                QMessageBox.warning(self, "No Valid IDs", "No valid UUIDs found.")
                return

            payload = {"serial": serial, "delete_map": delete_map, "folder": getattr(self, "_folder", "INBOX")}
            self._send_cmd("hive.email_check.delete_email", payload)

            self.mail_view.setPlainText(f"🗑 Requested delete for {len(delete_map)} message(s).")

            # Optionally refresh the list
            QTimer.singleShot(1000, lambda: self._request_page(self._pagination.get('current', 0)))

        except Exception as e:
            print(f"[EMAIL_CHECK][ERROR] delete_selected: {e}")

    def _load_email_connections(self):
        """Populate dropdown from the vault root (like EmailSend does)."""
        try:
            self.conn_selector.clear()
            self._connections = {}

            vault = VaultConnectionSingleton.get()
            # Fetch registry data from cockpit over pipe
            vault_data = vault.fetch_fresh(target="registry") or {}
            email_conns = vault_data.get("imap", {})

            if not email_conns:
                self.conn_selector.addItem("No email connections found", userData=None)
                print("[EMAIL_CHECK] No email accounts found in vault.")
                return

            for conn_id, data in email_conns.items():

                if not isinstance(data, dict):
                    continue

                serial = data.get("serial", "?")
                label = data.get("label", conn_id)
                user = data.get("incoming_username", "")
                host = data.get("incoming_server", "")
                port = data.get("incoming_port", "")
                uh = self._fmt_user_host(user, host)
                display = f"{label} ({uh}:{port})"

                info = {"conn_id": conn_id, "serial": serial, "cfg": data}
                self.conn_selector.addItem(display, userData=info)
                self._connections[conn_id] = info
                print(f"[EMAIL_CHECK] Added {label} serial={serial}")

            if self.conn_selector.count() > 0:
                self.conn_selector.currentIndexChanged.connect(self._on_connection_selected)
                self.conn_selector.setCurrentIndex(0)
                self._on_connection_selected(0)
            else:
                self.conn_selector.addItem("No incoming email accounts", userData=None)

        except Exception as e:
            print(f"[EMAIL_CHECK][ERROR] load_email_connections: {e}")

    def _temp_load_email_connections(self):
        self.conn_selector.addItem("No incoming email accounts", userData=None)


    def _on_connection_selected(self, index):
        """Update info box when a connection is selected."""
        try:
            data = self.conn_selector.itemData(index)
            if not data or not isinstance(data, dict):
                self.info_label.setText("No connection selected.")
                self._current_serial = None
                return

            cfg = data.get("cfg", {})
            serial = data.get("serial", "?")
            self._current_serial = serial
            # immediately check mailbox
            payload = {"serial": serial}

            self._send_cmd("hive.email_check.check_email", payload)

            self.info_label.setText(
                f"Server: <b>{cfg.get('incoming_server', '?')}</b><br>"
                f"Port: <b>{cfg.get('incoming_port', '?')}</b><br>"
                f"User: <b>{cfg.get('incoming_username', '?')}</b><br>"
                f"Serial: <b>{serial}</b>"
            )
            print(f"[EMAIL_CHECK] Selected connection {serial} → {cfg.get('incoming_server')}")

        except Exception as e:
            print(f"[EMAIL_CHECK][ERROR] on_connection_selected: {e}")

    def _check_now(self):
        try:
            index = self.conn_selector.currentIndex()
            data = self.conn_selector.itemData(index)
            if not data:
                QMessageBox.warning(self, "No Account Selected", "Please select an account first.")
                return

            # Handle tuple or dict userData
            serial = None
            if isinstance(data, tuple) and len(data) == 2:
                _, cfg = data
                serial = cfg.get("serial") or cfg.get("acct_serial")

            elif isinstance(data, dict):
                serial = data.get("serial") or data.get("acct_serial")

            if not serial:
                QMessageBox.warning(self, "Missing Serial", "This account has no serial number.")
                return

            # Send command to check the mailbox
            payload = {"serial": serial}
            self._send_cmd("hive.email_check.check_email", payload)

            # Ask for first 20 messages (list view)
            payload_list = {"serial": serial, "folder": "INBOX", "limit": self.page_limit}
            self._send_cmd("hive.email_check.list_mailbox", payload_list)

            self.mail_view.setPlainText(f"🔁 Checking mailbox ({serial})…")

        except Exception as e:
            print(f"[EMAIL_CHECK][ERROR] _check_now: {e}")

    # -------------------------------------------------------------------------
    # Command senders
    # -------------------------------------------------------------------------
    def _send_cmd(self, service, payload=None):
        """Emit a command packet safely, even with no payload."""
        try:
            payload = payload or {}  # ensure dict
            payload["session_id"] = self.session_id  # tag session
            pk = Packet()
            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": service,
                    "payload": payload,
                },
            })
            self.bus.emit(
                "outbound.message",
                session_id=self.session_id,
                channel="outgoing.command",
                packet=pk,
            )
            print(f"[EMAIL_CHECK][CMD] Sent → {service}")
        except Exception as e:
            emit_gui_exception_log("EmailCheck._send_cmd", e)

    def _load_servers(self):
        """Query the agent for currently configured IMAP servers."""
        self._send_cmd("hive.email_check.list_servers")

    def _check_mail(self):
        """Trigger immediate mailbox scan."""
        self._send_cmd("hive.email_check.check_mail")
        QMessageBox.information(self, "Email Check", "Triggered mail check.")

    def _view_selected(self):
        item = self.mail_list.currentItem()
        if not item:
            QMessageBox.warning(self, "No Selection", "Select an email to view.")
            return
        acct, fname = item.data(Qt.ItemDataRole.UserRole)
        payload = {"acct_id": acct, "filename": fname}
        self._send_cmd("hive.email_check.retrieve_mail", payload)


    def _add_server(self):
        
        acct_id, ok = QInputDialog.getText(self, "Add Server", "Server ID:")
        if ok and acct_id.strip():
            self._send_cmd("hive.email_check.add_server", {"id": acct_id.strip()})

    def _remove_server(self):
        
        acct_id, ok = QInputDialog.getText(self, "Remove Server", "Server ID to remove:")
        if ok and acct_id.strip():
            self._send_cmd("hive.email_check.remove_server", {"id": acct_id.strip()})

    def _purge_old(self):
        
        days, ok = QInputDialog.getInt(self, "Purge Old Mail", "Delete mails older than (days):", 30, 1, 365)
        if ok:
            self._send_cmd("hive.email_check.purge_old", {"days": days})
            QMessageBox.information(self, "Purge Complete", f"Requested purge older than {days} days.")

    def _open_manage_dialog(self):
        """Open the Manage Email Servers dialog that loads accounts automatically."""
        try:
            dlg = ManageServersDialog(self.session_id, self.bus, self.conn_selector)
            dlg.exec()
        except Exception as e:
            print(f"[EMAIL_CHECK][ERROR] open_manage_dialog: {e}")

    # -------------------------------------------------------------------------
    # Callback listener + pagination
    # -------------------------------------------------------------------------
    def _handle_load_email_accounts(self, payload):
        """Handle fresh account list pushed from EmailCheck agent."""
        try:
            content = payload.get("content", {})
            accounts = content.get("accounts", {})

            if not accounts:
                print("[EMAIL_CHECK] ⚠ No accounts returned from agent.")
                self.conn_selector.clear()
                self.conn_selector.addItem("No accounts loaded", userData=None)
                return

            print(f"[EMAIL_CHECK] 🔄 Loading {len(accounts)} account(s) from agent.")
            self.conn_selector.blockSignals(True)
            self.conn_selector.clear()
            self._connections = {}

            for serial, cfg in accounts.items():
                label = cfg.get("label") or cfg.get("incoming_username", serial)
                host = cfg.get("incoming_server", "?")
                port = cfg.get("incoming_port", "?")
                user = cfg.get("incoming_username", "?")
                uh = self._fmt_user_host(user, host)
                display = f"acct: {serial} ★ host: {uh}:{port}"

                info = {"conn_id": serial, "serial": serial, "cfg": cfg}
                self.conn_selector.addItem(display, userData=info)
                self._connections[serial] = info

            self.conn_selector.blockSignals(False)

            # auto-select the first one
            if self.conn_selector.count() > 0:
                self.conn_selector.setCurrentIndex(0)
                self._on_connection_selected(0)

            self.conn_selector.blockSignals(False)
            self.conn_selector.currentIndexChanged.connect(self._on_connection_selected)

        except Exception as e:
            print(f"[EMAIL_CHECK][ERROR] handle_load_email_accounts: {e}")

    def _handle_mailbox_callback(self, session_id, channel, source, payload, **_):
        """Render incoming mailbox results from agent callback."""
        try:
            content = payload.get("content", {})
            messages = content.get("messages", [])
            pagination = content.get("pagination", {})
            folder = content.get("folder", "INBOX")

            # stash data for GUI thread
            self._pending_update = (folder, messages, pagination)
            QMetaObject.invokeMethod(
                self, "_apply_mailbox_update",
                Qt.ConnectionType.QueuedConnection,
            )
        except Exception as e:
            print(f"[EMAIL_CHECK][ERROR] handle_mailbox_callback: {e}")

    @pyqtSlot()
    def _apply_mailbox_update(self):
        """Runs on the GUI thread to update widgets safely."""
        if not hasattr(self, "_pending_update"):
            return
        folder, messages, pagination = self._pending_update

        self.mail_list.clear()
        for m in messages:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m.get("timestamp", 0)))
            text = f"{folder}: {ts} — {m['uuid']} ({m['size']} bytes)"
            self.mail_list.addItem(text)

        total = int(pagination.get("total", len(messages)))
        current = int(pagination.get("current", 0))
        limit = int(pagination.get("limit", len(messages)))

        if total <= 0:
            display_range = "0 of 0"
        else:
            shown_from = max(1, current + 1)
            shown_to = min(current + limit, total)
            if shown_from >= shown_to:
                display_range = f"{shown_from} of {total}"
            else:
                display_range = f"{shown_from}-{shown_to} of {total}"


        self.mail_view.setPlainText(f"✅ {folder} updated — showing {display_range} messages")
        self._current_serial = getattr(self, "_current_serial", None)
        self._pagination = pagination
        self._folder = folder
        self._update_nav_buttons()

    def _update_nav_buttons(self):
        """Enable or disable Prev/Next based on pagination data (safe for first load)."""
        try:
            if not hasattr(self, "_pagination") or not isinstance(self._pagination, dict):
                self.prev_btn.setEnabled(False)
                self.next_btn.setEnabled(False)
                return

            total = int(self._pagination.get("total", 0))
            current = int(self._pagination.get("current", 0))
            limit = int(self._pagination.get("limit", self.page_limit))
            next_offset = self._pagination.get("next")

            # Graceful handling of empty or single-page
            if total <= limit:
                self.prev_btn.setEnabled(False)
                self.next_btn.setEnabled(False)
                return

            self.prev_btn.setEnabled(current > 0)
            self.next_btn.setEnabled(next_offset is not None and current + limit < total)

        except Exception as e:
            print(f"[EMAIL_CHECK][ERROR] update_nav_buttons: {e}")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)

    def _prev_page(self):
        """Go back one page safely."""
        try:
            if not hasattr(self, "_pagination"):
                return
            current = int(self._pagination.get("current", 0))
            limit = int(self._pagination.get("limit", self.page_limit))
            new_offset = max(0, current - limit)
            print(f"[DEBUG] PREV_PAGE → offset={new_offset}")
            self._request_page(new_offset)
        except Exception as e:
            print(f"[EMAIL_CHECK][ERROR] prev_page: {e}")

    def _next_page(self):
        """Go forward one page safely."""
        try:
            if not hasattr(self, "_pagination"):
                return
            next_offset = self._pagination.get("next")
            if next_offset is None:
                return
            print(f"[DEBUG] NEXT_PAGE → offset={next_offset}")
            self._request_page(next_offset)
        except Exception as e:
            print(f"[EMAIL_CHECK][ERROR] next_page: {e}")

    def _request_page(self, offset):
        if not getattr(self, "_current_serial", None):
            return
        payload = {
            "serial": self._current_serial,
            "folder": getattr(self, "_folder", "INBOX"),
            "limit": self.page_limit,
            "offset": offset,
        }
        self._send_cmd("hive.email_check.list_mailbox", payload)

    def _on_message_selected(self, item):
        """User clicked a message — request its body."""
        try:
            text = item.text()

            m = re.search(r"([0-9a-fA-F\-]{36})", text)
            if not m:
                QMessageBox.warning(self, "Invalid", "Cannot parse message UUID.")
                return

            uuid_str = m.group(1)
            serial = getattr(self, "_current_serial", None)
            if not serial:
                QMessageBox.warning(self, "No Account", "Missing account serial.")
                return

            payload = {"serial": serial, "uuid": uuid_str, "mode": "headers"}
            self._send_cmd("hive.email_check.retrieve_email", payload)
            self.mail_view.setPlainText("Fetching message…")
        except Exception as e:
            print(f"[EMAIL_CHECK][ERROR] _on_message_selected: {e}")

    def _handle_retrieve_callback(self, session_id, channel, source, payload, **_):
        try:
            outer = payload.get("content", {})
            email = outer.get("content", outer)  # <-- this grabs inner content cleanly
            self._pending_body = email
            QMetaObject.invokeMethod(
                self, "_apply_retrieve_update",
                Qt.ConnectionType.QueuedConnection,
            )
        except Exception as e:
            print(f"[EMAIL_CHECK][ERROR] retrieve callback: {e}")

    @pyqtSlot()
    def _apply_retrieve_update(self):
        """Render the parsed email in a single formatted debug view."""
        if not hasattr(self, "_pending_body"):
            return

        email = self._pending_body
        try:
            # Reuse parser logic for inline preview (non-popup)
            parser = EmailDisplayParser(parent=self)
            html_preview = parser.generate_html(email)  # new helper we'll add
            self.mail_view.setHtml(html_preview)
        except Exception as e:
            self.mail_view.setPlainText(f"[ERROR displaying message] {e}")

    def _show_msg_full(self):
        """Show the raw email output in a popup dialog."""
        try:
            # Ensure there is data to display
            if not self._pending_body:
                print("No raw email body to show.")
                return  # Exit if there's no email data

            # Create the dialog (without preloading data)
            dialog = EmailDisplayParser(parent=self, title="📧 Parsed Email")

            # Dynamically load the email data
            dialog.render_data(self._pending_body)

            # Show the dialog modally
            dialog.exec()

        except Exception as e:
            print(f"Error showing raw output: {e}")

    # -------------------------------------------------------------------------
    def get_panel_buttons(self):
        return [PanelButton("📨", "EmailCheck", lambda: self.session_window.show_specialty_panel(self))]

    # ---------------------------------------------------------
    # Bus Handlers (persistent)
    # ---------------------------------------------------------
    def _connect_signals(self):

        """Attach bus listeners."""
        try:
            if self._signals_connected:
                return
            self._signals_connected = True

            scoped = f"inbound.verified.check_mail.cmd_list_mailbox"
            self.bus.on(scoped, self._handle_mailbox_callback)
            scoped = f"inbound.verified.check_mail.cmd_retrieve_email"
            self.bus.on(scoped, self._handle_retrieve_callback)
            scoped = f"inbound.verified.check_mail.load_email_accounts"
            self.bus.on(scoped, self._handle_load_email_accounts)

        except Exception as e:
            emit_gui_exception_log("EmailCheck._connect_signals", e)

    def _disconnect_signals(self):
        """Detach bus listeners and clear any buffered lines."""
        pass

    def _on_close(self):
        try:
            if self._signals_connected:
                self._signals_connected = False

                scoped = f"inbound.verified.check_mail.cmd_list_mailbox"
                self.bus.off(scoped, self._handle_mailbox_callback)
                scoped = f"inbound.verified.check_mail.cmd_retrieve_email"
                self.bus.off(scoped, self._handle_retrieve_callback)
                scoped = f"inbound.verified.check_mail.load_email_accounts"
                self.bus.off(scoped, self._handle_load_email_accounts)

        except Exception as e:
            emit_gui_exception_log("EmailCheck._disconnect_signals", e)
