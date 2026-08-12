# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import time
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit, QMessageBox, QComboBox, QGroupBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QStyle
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.vault.services.vault_connection_singleton import VaultConnectionSingleton

class EmailSend(PhoenixPanelInterface):
    cache_panel = True

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self.setLayout(self._build_layout())
        self.node=node

    def _build_layout(self):
        try:
            layout = QVBoxLayout()

            # === Connection Dropdown ===
            self.conn_selector = QComboBox()
            layout.addWidget(QLabel("Select Email Connection"))
            layout.addWidget(self.conn_selector)

            # === Connection Section ===
            conn_box = QGroupBox("📡 SMTP Connection")
            conn_layout = QVBoxLayout()

            row1 = QHBoxLayout()
            row1.addWidget(QLabel("SMTP Host"))
            self.smtp_server = QLineEdit()
            row1.addWidget(self.smtp_server)
            conn_layout.addLayout(row1)

            row2 = QHBoxLayout()
            row2.addWidget(QLabel("SMTP Port"))
            self.smtp_port = QLineEdit()
            row2.addWidget(self.smtp_port)
            conn_layout.addLayout(row2)

            row3 = QHBoxLayout()
            row3.addWidget(QLabel("From (email)"))
            self.smtp_user = QLineEdit()
            row3.addWidget(self.smtp_user)
            conn_layout.addLayout(row3)

            # === To (Email) Row with Save/Delete ===
            row4 = QHBoxLayout()
            row4.addWidget(QLabel("To (email)"))

            self.to_address = QLineEdit()
            self.to_address.setSizePolicy(self.smtp_user.sizePolicy())
            row4.addWidget(self.to_address, stretch=1)
            conn_layout.addLayout(row4)

            conn_box.setLayout(conn_layout)
            layout.addWidget(conn_box)



            pw_row = QHBoxLayout()
            pw_row.addWidget(QLabel("Password"))
            self.smtp_pass = QLineEdit()
            self.smtp_pass.setEchoMode(QLineEdit.EchoMode.Password)
            self.view_pass_btn = QPushButton("👁 View")
            self.view_pass_btn.setCheckable(True)
            self.view_pass_btn.setFixedWidth(70)
            self.view_pass_btn.toggled.connect(self._toggle_password_visibility)

            pw_row.addWidget(self.smtp_pass)
            pw_row.addWidget(self.view_pass_btn)
            conn_layout.addLayout(pw_row)



            # === Message Section ===
            msg_box = QGroupBox("✉️ Message Details")
            msg_layout = QVBoxLayout()




            # Save button
            #self.save_to_btn = QPushButton()
            #self.save_to_btn.setToolTip("Save this email to vault")
            #self.save_to_btn.setFixedSize(30, 30)
            #self.save_to_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))

            # Delete button
            #self.del_to_btn = QPushButton()
            #self.del_to_btn.setToolTip("Delete selected email from vault")
            #self.del_to_btn.setFixedSize(30, 30)
            #self.del_to_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))

            # vertical centering trick
            #btn_col = QVBoxLayout()
            #btn_col.setContentsMargins(0, 0, 0, 0)
            #btn_col.setSpacing(2)
            #btn_col.addWidget(self.save_to_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
            #btn_col.addWidget(self.del_to_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

            #row4.addLayout(btn_col)
            #msg_layout.addLayout(row4)

            row5 = QHBoxLayout()
            row5.addWidget(QLabel("Subject"))
            self.subject = QLineEdit()
            row5.addWidget(self.subject)
            msg_layout.addLayout(row5)

            msg_layout.addWidget(QLabel("Body:"))
            self.body = QTextEdit()
            msg_layout.addWidget(self.body)

            msg_box.setLayout(msg_layout)
            layout.addWidget(msg_box)

            # === Actions ===
            self.send_btn = QPushButton("📧 Send Email")
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            btn_row.addWidget(self.send_btn)
            layout.addLayout(btn_row)

            # === Bind Actions ===
            self.send_btn.clicked.connect(self._send_email)
            self.conn_selector.currentIndexChanged.connect(self._on_connection_selected)

            # --- Load saved recipients on startup ---
            self._load_saved_recipients()

            # --- Bind save/delete ---
            #self.save_to_btn.clicked.connect(self._save_current_recipient)
            #self.del_to_btn.clicked.connect(self._delete_current_recipient)

            # === Preload Connections ===
            self._temp_load_email_connections()

            return layout
        except Exception as e:
            emit_gui_exception_log("EmailSend._build_layout", e)

    def _make_pass_row(self):
        """Return a layout row containing password box + view button."""
        row = QHBoxLayout()
        row.addWidget(QLabel("Password"))
        row.addWidget(self.smtp_pass)
        row.addWidget(self.view_pass_btn)
        return row

    def _toggle_password_visibility(self, checked):
        self.smtp_pass.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        self.view_pass_btn.setText("🙈 Hide" if checked else "👁 View")


    def _temp_load_email_connections(self):
        """
        Commander Edition — Registry-Aware Email Connection Loader
        ----------------------------------------------------------
        Populates dropdown with all SMTP routes stored under:
            vault.registry.smtp
        Fallback: adds the agent's inline SMTP config if defined.
        """
        try:
            self.conn_selector.clear()
            self._connections = {}

            vault = VaultConnectionSingleton.get()

            # Fetch registry data from cockpit over pipe
            vault_data = vault.fetch_fresh(target="registry") or {}
            smtp_registry = vault_data.get("smtp", {})

            print(f"{smtp_registry}")

            # --- Load all SMTP registry objects ---
            if isinstance(smtp_registry, dict) and smtp_registry:
                for serial, entry in smtp_registry.items():
                    if not isinstance(entry, dict):
                        continue

                    label = entry.get("label", serial)
                    addr = entry.get("smtp_username") or entry.get("smtp_server", "unknown")
                    display = f"{label} ({addr})"

                    self.conn_selector.addItem(display, userData=(serial, entry))
                    self._connections[serial] = entry
                    print(f"[EMAIL PANEL] Added registry SMTP route: {display}")

            # --- Default Selection ---
            if self.conn_selector.count() > 0:
                self.conn_selector.setCurrentIndex(0)
                self._on_connection_selected(self.conn_selector.currentIndex())
                print(f"[EMAIL PANEL] Default SMTP: {self.conn_selector.currentText()}")
            else:
                self.conn_selector.addItem("No SMTP connections found", userData=None)
                print("[EMAIL PANEL] No SMTP routes detected in registry or agent config.")

        except Exception as e:
            emit_gui_exception_log("EmailSend._temp_load_email_connections", e)

    def _load_saved_recipients(self):
        """Load saved recipient emails from the current deployment, or vault fallback."""
        try:
            vault = VaultConnectionSingleton.get()

            # ry from the current deployment first
            dep = vault.read_deployment() or {}
            recipients = (
                dep.get("email_recipients", {}).get("recipients", [])
                if isinstance(dep, dict) else []
            )

            # Fallback to vault query if none found
            if not recipients:
                vault_data = vault.fetch_fresh(target="email_recipients") or {}
                recipients = vault_data.get("recipients", [])

            # Populate dropdown
            self.to_address.clear()
            for addr in recipients:
                if addr:
                    self.to_address.addItem(addr)

            print(f"[EMAIL PANEL] Loaded {len(recipients)} saved recipients from deployment/vault.")

        except Exception as e:
            print(f"[EMAIL PANEL][WARN] Failed to load saved recipients: {e}")

    def _save_current_recipient(self):
        """Save the current 'To' address into vault list."""
        email = self.to_address.currentText().strip()
        if not email:
            return
        try:
            vault = VaultConnectionSingleton.get()
            existing = vault.read_deployment().get("email_recipients", {}).get("recipients", [])
            if email not in existing:
                existing.append(email)
                vault.update_field("email_recipients", {"recipients": existing})
                print(f"[EMAIL PANEL] Saved new recipient: {email}")
            self._load_saved_recipients()
        except Exception as e:
            print(f"[EMAIL PANEL][ERROR] Failed to save recipient: {e}")

    def _delete_current_recipient(self):
        """Delete selected 'To' address from vault list."""
        email = self.to_address.currentText().strip()
        if not email:
            return
        try:
            vault = VaultConnectionSingleton.get()
            existing = vault.read_deployment().get("email_recipients", {}).get("recipients", [])
            if email in existing:
                existing.remove(email)
                vault.update_field("email_recipients", {"recipients": existing})
                print(f"[EMAIL PANEL] Deleted recipient: {email}")
            self._load_saved_recipients()
        except Exception as e:
            print(f"[EMAIL PANEL][ERROR] Failed to delete recipient: {e}")

    def _on_connection_selected(self, index):
        """Auto-fill SMTP fields when user selects a connection."""
        try:
            if index < 0:
                return
            data = self.conn_selector.itemData(index)
            if not data:
                return

            # userData can be (conn_id, cfg) or just cfg depending on how loaded
            if isinstance(data, tuple) and len(data) == 2:
                _, cfg = data
            elif isinstance(data, dict):
                cfg = data
            else:
                print(f"[EMAIL PANEL][WARN] Unknown connection data format: {data}")
                return

            # fill in all known SMTP/IMAP fields
            self.smtp_server.setText(str(cfg.get("smtp_server", "")))
            self.smtp_port.setText(str(cfg.get("smtp_port", "")))
            self.smtp_user.setText(str(cfg.get("smtp_username", "")))
            self.smtp_pass.setText(str(cfg.get("smtp_password", "")))

            # optional pre-fill for convenience
            if cfg.get("smtp_to"):
                self.to_address.setText(cfg.get("smtp_to", ""))

            else:
                self.to_address.clear()

            self.subject.clear()
            self.body.clear()

            print(f"[EMAIL PANEL] Populated fields from connection: {cfg.get('smtp_server')}")

        except Exception as e:
            print(f"[EMAIL PANEL][ERROR] Failed to populate fields: {e}")

    def _send_email(self):
        try:

            pk = Packet()
            pk.set_data({
                "handler": "cmd_service_request",
                "ts": time.time(),
                "content": {
                    "service": "send_email.send",
                    "payload": {
                        "smtp_server": self.smtp_server.text().strip(),
                        "smtp_port": self.smtp_port.text().strip(),
                        "from": self.smtp_user.text().strip(),
                        "password": self.smtp_pass.text().strip(),
                        "to": self.to_address.text().strip(),
                        "subject": self.subject.text().strip(),
                        "body": self.body.toPlainText().strip(),
                    }
                }
            })

            self.bus.emit("outbound.message", session_id=self.session_id, channel="outgoing.command", packet=pk)

            QMessageBox.information(self, "Email Sent", "Email sent to agent for delivery.")

        except Exception as e:
            emit_gui_exception_log("EmailSend._send_email", e)
            QMessageBox.critical(self, "Error", f"Failed to send email: {e}")

    def _connect_signals(self):
        pass

    def _disconnect_signals(self):
        pass

    def get_panel_buttons(self):
        return [PanelButton("📧", "EmailSend", lambda: self.session_window.show_specialty_panel(self))]
