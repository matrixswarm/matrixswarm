# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from datetime import datetime

from Crypto.PublicKey import RSA
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QTextEdit,
    QMessageBox, QComboBox, QGroupBox, QCompleter, QTabWidget, QWidget,
    QFormLayout
)
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QStyle
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.modules.vault.services.vault_connection_singleton import VaultConnectionSingleton
from matrix_gui.core.utils.crypto_utils import (
    decrypt_with_ephemeral_aes,
    verify_signed_payload,
)


ENCRYPTED_ALERT_MARKER = "MATRIXSWARM-ENCRYPTED-ALERT-V1"
ENCRYPTED_ALERT_HANDLER = "email_send.alert"


def decode_alert_envelope(message_text: str) -> dict:
    """Recover a Base64 JSON alert envelope from pasted email text."""
    if not isinstance(message_text, str) or not message_text.strip():
        raise ValueError("Paste an encrypted alert message first.")

    raw = message_text.strip()
    candidates = []

    marker_index = raw.find(ENCRYPTED_ALERT_MARKER)
    if marker_index >= 0:
        after_marker = raw[marker_index + len(ENCRYPTED_ALERT_MARKER):]
        payload_lines = []
        for raw_line in after_marker.splitlines():
            line = re.sub(r"^\s*>\s?", "", raw_line).strip()
            if not line:
                continue
            if not re.fullmatch(r"[A-Za-z0-9+/=]+", line):
                if payload_lines:
                    break
                continue
            payload_lines.append(line)
        if payload_lines:
            # Try the full block first, then progressively remove trailing
            # lines. Some mail clients append a footer made only of letters,
            # which is syntactically Base64 but is not part of the envelope.
            candidates.extend(
                "".join(payload_lines[:end])
                for end in range(len(payload_lines), 0, -1)
            )

    # Also accept a Base64 envelope without the marker, including a long block
    # copied out of a mail client. Authentication below is the trust boundary.
    compact = "".join(raw.split())
    candidates.append(compact)
    candidates.extend(re.findall(r"[A-Za-z0-9+/=]{80,}", raw))

    last_error = None
    for encoded in dict.fromkeys(candidates):
        try:
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
            envelope = json.loads(decoded)
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
            last_error = error
            continue

        if isinstance(envelope, dict) and isinstance(envelope.get("content"), dict):
            return envelope

    raise ValueError("The alert is not a valid Base64 JSON envelope.") from last_error


def _optional_timestamp(value, field_name: str):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"The signed alert {field_name} timestamp is invalid."
        ) from error


def decrypt_alert_message(
    message_text: str,
    trusted_serial: str,
    sender_pubkey,
    phoenix_privkey,
    now=None,
) -> dict:
    """Authenticate and decrypt an archived alert without replay rejection."""
    envelope = decode_alert_envelope(message_text)
    signed_wrapper = envelope["content"]

    if not isinstance(trusted_serial, str) or not trusted_serial.strip():
        raise ValueError("The current agent has no trusted serial.")
    trusted_serial = trusted_serial.strip()

    serial = signed_wrapper.get("serial")
    if not isinstance(serial, str) or not hmac.compare_digest(
        serial, trusted_serial
    ):
        raise ValueError("The alert serial does not match the current agent.")

    signature = signed_wrapper.get("sig")
    if not isinstance(signature, str) or not signature.strip():
        raise ValueError("The signed alert signature is missing.")

    expected_hash = hashlib.sha256(
        f"{serial}email-send-message".encode("utf-8")
    ).hexdigest()
    message_hash = signed_wrapper.get("hash")
    if not isinstance(message_hash, str) or not hmac.compare_digest(
        message_hash, expected_hash
    ):
        raise ValueError("The signed alert purpose hash is invalid.")

    if not sender_pubkey or not phoenix_privkey:
        raise ValueError("The current agent certificate pair is incomplete.")
    sender_key = (
        RSA.import_key(sender_pubkey.encode("utf-8"))
        if isinstance(sender_pubkey, str)
        else RSA.import_key(sender_pubkey)
    )
    verify_signed_payload(
        {key: value for key, value in signed_wrapper.items() if key != "sig"},
        signature,
        sender_key,
    )

    encrypted_content = signed_wrapper.get("content")
    if not isinstance(encrypted_content, dict):
        raise ValueError("The encrypted alert content is missing.")

    clear_payload = decrypt_with_ephemeral_aes(encrypted_content, phoenix_privkey)
    if isinstance(clear_payload, bytes):
        try:
            clear_payload = clear_payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("The decrypted alert is not UTF-8 text.") from error
    if isinstance(clear_payload, str):
        try:
            clear_payload = json.loads(clear_payload)
        except json.JSONDecodeError as error:
            raise ValueError("The decrypted alert is not valid JSON.") from error

    if not isinstance(clear_payload, dict):
        raise ValueError("The decrypted alert payload is invalid.")
    if clear_payload.get("handler") != ENCRYPTED_ALERT_HANDLER:
        raise ValueError("The decrypted payload is not an email alert.")

    content = clear_payload.get("content")
    if not isinstance(content, dict):
        raise ValueError("The decrypted alert message is missing.")

    sent_at = _optional_timestamp(
        signed_wrapper.get("timestamp", content.get("timestamp")), "sent"
    )
    expires_at = _optional_timestamp(signed_wrapper.get("expires"), "expiry")
    current_time = float(time.time() if now is None else now)

    return {
        "subject": str(content.get("subject", "")),
        "body": str(content.get("body", "")),
        "origin": str(content.get("origin", "not specified")),
        "level": str(content.get("level", "info")),
        "serial": serial,
        "sent_at": sent_at,
        "expires_at": expires_at,
        "expired": expires_at is not None and current_time > expires_at,
    }


def format_alert_timestamp(value) -> str:
    """Format a signed epoch timestamp in the operator's local timezone."""
    if value is None:
        return "Not supplied"
    return datetime.fromtimestamp(float(value)).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    )

class EmailSend(PhoenixPanelInterface):
    cache_panel = True

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self.setLayout(self._build_layout())
        self.node=node

    def _build_layout(self):
        try:
            outer_layout = QVBoxLayout()
            self.tabs = QTabWidget()
            self.send_tab = QWidget()
            layout = QVBoxLayout(self.send_tab)

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

            self.decrypt_tab = self._build_decrypt_tab()
            self.tabs.addTab(self.send_tab, "📧 Send Message")
            self.tabs.addTab(self.decrypt_tab, "🔓 Decrypt Message")
            self.tabs.currentChanged.connect(self._on_email_tab_changed)
            outer_layout.addWidget(self.tabs)

            return outer_layout
        except Exception as e:
            emit_gui_exception_log("EmailSend._build_layout", e)

    def _build_decrypt_tab(self):
        """Build the paste-and-decrypt authenticated alert reader."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        instructions = QLabel(
            "Paste the complete encrypted email message below, then click "
            "Decrypt. Phoenix uses this agent's active deployment certificate "
            "to authenticate and decrypt it. Expired alerts remain viewable."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        input_box = QGroupBox("🔐 Encrypted Message")
        input_layout = QVBoxLayout(input_box)
        self.encrypted_alert_input = QTextEdit()
        self.encrypted_alert_input.setPlaceholderText(
            "Paste the entire email here, beginning with\n"
            "MATRIXSWARM-ENCRYPTED-ALERT-V1"
        )
        input_layout.addWidget(self.encrypted_alert_input)
        layout.addWidget(input_box)

        action_row = QHBoxLayout()
        self.clear_decrypt_btn = QPushButton("Clear")
        self.decrypt_alert_btn = QPushButton("🔓 Decrypt")
        action_row.addStretch()
        action_row.addWidget(self.clear_decrypt_btn)
        action_row.addWidget(self.decrypt_alert_btn)
        layout.addLayout(action_row)

        verification_box = QGroupBox("✅ Verification")
        verification_layout = QFormLayout(verification_box)
        self.decrypt_status = QLabel("Not verified")
        self.decrypt_sent_at = QLabel("—")
        self.decrypt_expires_at = QLabel("—")
        self.decrypt_sender = QLabel("—")
        verification_layout.addRow("Status:", self.decrypt_status)
        verification_layout.addRow("Sent:", self.decrypt_sent_at)
        verification_layout.addRow("Expires:", self.decrypt_expires_at)
        verification_layout.addRow("Sender:", self.decrypt_sender)
        layout.addWidget(verification_box)

        message_box = QGroupBox("✉️ Decrypted Message")
        message_layout = QFormLayout(message_box)
        self.decrypted_subject = QLineEdit()
        self.decrypted_subject.setReadOnly(True)
        self.decrypted_body = QTextEdit()
        self.decrypted_body.setReadOnly(True)
        message_layout.addRow("Subject:", self.decrypted_subject)
        message_layout.addRow("Body:", self.decrypted_body)
        layout.addWidget(message_box)

        self.decrypt_alert_btn.clicked.connect(self._decrypt_alert)
        self.clear_decrypt_btn.clicked.connect(self._clear_decrypt)
        return tab

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

    def on_panel_activated(self):
        """Wake the editors after this cached panel enters the native stack."""
        if self.tabs.currentWidget() is self.decrypt_tab:
            self.encrypted_alert_input.ensurePolished()
            self.encrypted_alert_input.setFocus(Qt.FocusReason.OtherFocusReason)
            self.encrypted_alert_input.viewport().update()
            return

        self.subject.ensurePolished()
        self.body.ensurePolished()
        self.subject.setFocus(Qt.FocusReason.OtherFocusReason)
        self.subject.update()
        self.body.viewport().update()

    def _on_email_tab_changed(self, _index):
        """Move keyboard focus to the primary editor on the selected tab."""
        self.on_panel_activated()

    def _get_current_alert_keys(self):
        uid = (self.node or {}).get("universal_id")
        if not uid:
            raise RuntimeError("Current EmailSend agent has no universal_id.")

        vault = VaultConnectionSingleton.get()
        deployment = vault.fetch_fresh(target="deployment") or {}

        agent = next(
            (
                item for item in deployment.get("agents", [])
                if item.get("universal_id") == uid
            ),
            None,
        )
        if not agent:
            raise RuntimeError(f"Current agent {uid!r} is absent from the deployment.")

        serial = agent.get("serial")
        signing = (
            deployment
            .get("certs", {})
            .get(uid, {})
            .get("signing", {})
        )

        sender_pubkey = signing.get("pubkey")
        phoenix_privkey = signing.get("remote_privkey")

        if not serial or not sender_pubkey or not phoenix_privkey:
            raise RuntimeError(
                f"Signing/decryption material is incomplete for {uid!r}."
            )

        return serial, sender_pubkey, phoenix_privkey

    def _decrypt_alert(self):
        """Verify, decrypt, and display one pasted encrypted alert."""
        try:
            serial, sender_pubkey, phoenix_privkey = self._get_current_alert_keys()
            result = decrypt_alert_message(
                self.encrypted_alert_input.toPlainText(),
                serial,
                sender_pubkey,
                phoenix_privkey,
            )

            if result["expired"]:
                self.decrypt_status.setText(
                    "✅ Signature verified — ⚠ Expired (view-only)"
                )
                self.decrypt_status.setStyleSheet("color: #ffbf47;")
            else:
                self.decrypt_status.setText("✅ Signature verified — Current")
                self.decrypt_status.setStyleSheet("color: #00e6a8;")

            self.decrypt_sent_at.setText(format_alert_timestamp(result["sent_at"]))
            self.decrypt_expires_at.setText(
                format_alert_timestamp(result["expires_at"])
            )
            self.decrypt_sender.setText(
                f"{result['origin']}  •  {result['level']}  •  "
                f"serial {result['serial'][:12]}…"
            )
            self.decrypted_subject.setText(result["subject"])
            self.decrypted_body.setPlainText(result["body"])

        except Exception as e:
            self._clear_decrypt_result()
            self.decrypt_status.setText("❌ Verification/decryption failed")
            self.decrypt_status.setStyleSheet("color: #ff5c5c;")
            emit_gui_exception_log("EmailSend._decrypt_alert", e)
            QMessageBox.warning(
                self,
                "Encrypted Alert Rejected",
                "Phoenix could not authenticate and decrypt this message.\n\n"
                f"{e}",
            )

    def _clear_decrypt_result(self):
        self.decrypt_sent_at.setText("—")
        self.decrypt_expires_at.setText("—")
        self.decrypt_sender.setText("—")
        self.decrypted_subject.clear()
        self.decrypted_body.clear()

    def _clear_decrypt(self):
        self.encrypted_alert_input.clear()
        self._clear_decrypt_result()
        self.decrypt_status.setText("Not verified")
        self.decrypt_status.setStyleSheet("")
        self.encrypted_alert_input.setFocus(Qt.FocusReason.OtherFocusReason)

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

            # QLineEdit has no addItem API. Preserve free-form entry and offer
            # vault recipients through a case-insensitive completion popup.
            recipients = [str(addr).strip() for addr in recipients if str(addr).strip()]
            self._recipient_completer = QCompleter(recipients, self.to_address)
            self._recipient_completer.setCaseSensitivity(
                Qt.CaseSensitivity.CaseInsensitive
            )
            self._recipient_completer.setCompletionMode(
                QCompleter.CompletionMode.PopupCompletion
            )
            self.to_address.setCompleter(self._recipient_completer)

            print(f"[EMAIL PANEL] Loaded {len(recipients)} saved recipients from deployment/vault.")

        except Exception as e:
            print(f"[EMAIL PANEL][WARN] Failed to load saved recipients: {e}")

    def _save_current_recipient(self):
        """Save the current 'To' address into vault list."""
        email = self.to_address.text().strip()
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
        email = self.to_address.text().strip()
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
