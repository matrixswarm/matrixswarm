# Authored by Daniel F MacDonald and ChatGPT aka The Generals
"""Authenticated manual reader for encrypted MatrixSwarm Telegram alerts."""

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
from datetime import datetime

from Crypto.PublicKey import RSA
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import (
    PhoenixPanelInterface,
)
from matrix_gui.core.utils.crypto_utils import (
    decrypt_with_ephemeral_aes,
    verify_signed_payload,
)
from matrix_gui.modules.vault.services.vault_connection_singleton import (
    VaultConnectionSingleton,
)


ENCRYPTED_ALERT_MARKER = "MATRIXSWARM-ENCRYPTED-ALERT-V1"
ENCRYPTED_ALERT_HANDLER = "telegram_relay.alert"
TELEGRAM_ALERT_HASH_SUFFIX = "telegram-relay-message"


def decode_alert_envelope(message_text: str) -> dict:
    """Recover a Base64 JSON alert envelope from copied Telegram text."""
    if not isinstance(message_text, str) or not message_text.strip():
        raise ValueError("Paste an encrypted Telegram alert first.")

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
            # Telegram clients can wrap a copied Base64 block. Try the entire
            # block first, then progressively discard any trailing footer line.
            candidates.extend(
                "".join(payload_lines[:end])
                for end in range(len(payload_lines), 0, -1)
            )

    # Also accept the raw Base64 envelope by itself. Cryptographic validation
    # below remains the trust boundary.
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

    raise ValueError("The Telegram alert is not a valid Base64 JSON envelope.") from last_error


def _optional_timestamp(value, field_name: str):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"The signed Telegram alert {field_name} timestamp is invalid."
        ) from error


def decrypt_alert_message(
    message_text: str,
    trusted_serial: str,
    sender_pubkey,
    phoenix_privkey,
    now=None,
) -> dict:
    """Authenticate and decrypt an archived Telegram alert.

    This deliberately avoids live replay rejection: operators may decrypt a
    stored alert more than once. Serial, purpose, signature, authenticated
    encryption, and inner-handler validation remain mandatory.
    """
    envelope = decode_alert_envelope(message_text)
    signed_wrapper = envelope["content"]

    if not isinstance(trusted_serial, str) or not trusted_serial.strip():
        raise ValueError("The current Telegram agent has no trusted serial.")
    trusted_serial = trusted_serial.strip()

    serial = signed_wrapper.get("serial")
    if not isinstance(serial, str) or not hmac.compare_digest(
        serial, trusted_serial
    ):
        raise ValueError("The Telegram alert serial does not match the current agent.")

    signature = signed_wrapper.get("sig")
    if not isinstance(signature, str) or not signature.strip():
        raise ValueError("The signed Telegram alert signature is missing.")

    expected_hash = hashlib.sha256(
        f"{serial}{TELEGRAM_ALERT_HASH_SUFFIX}".encode("utf-8")
    ).hexdigest()
    message_hash = signed_wrapper.get("hash")
    if not isinstance(message_hash, str) or not hmac.compare_digest(
        message_hash, expected_hash
    ):
        raise ValueError("The signed Telegram alert purpose hash is invalid.")

    if not sender_pubkey or not phoenix_privkey:
        raise ValueError("The current Telegram agent certificate pair is incomplete.")

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
        raise ValueError("The encrypted Telegram alert content is missing.")

    clear_payload = decrypt_with_ephemeral_aes(encrypted_content, phoenix_privkey)
    if isinstance(clear_payload, bytes):
        try:
            clear_payload = clear_payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("The decrypted Telegram alert is not UTF-8 text.") from error
    if isinstance(clear_payload, str):
        try:
            clear_payload = json.loads(clear_payload)
        except json.JSONDecodeError as error:
            raise ValueError("The decrypted Telegram alert is not valid JSON.") from error

    if not isinstance(clear_payload, dict):
        raise ValueError("The decrypted Telegram alert payload is invalid.")
    if clear_payload.get("handler") != ENCRYPTED_ALERT_HANDLER:
        raise ValueError("The decrypted payload is not a Telegram relay alert.")

    content = clear_payload.get("content")
    if not isinstance(content, dict):
        raise ValueError("The decrypted Telegram alert message is missing.")

    sent_at = _optional_timestamp(
        signed_wrapper.get("timestamp", content.get("timestamp")), "sent"
    )
    expires_at = _optional_timestamp(signed_wrapper.get("expires"), "expiry")
    current_time = float(time.time() if now is None else now)

    return {
        "message": str(content.get("message", "")),
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


class TelegramRelay(PhoenixPanelInterface):
    """Paste, authenticate, and decrypt encrypted Telegram relay alerts."""

    cache_panel = True

    def __init__(self, session_id, bus=None, node=None, session_window=None):
        super().__init__(session_id, bus, node=node, session_window=session_window)
        self.setLayout(self._build_layout())

    def _build_layout(self):
        layout = QVBoxLayout()

        instructions = QLabel(
            "Paste the complete encrypted Telegram alert below, then click "
            "Decrypt. Phoenix uses this agent's active deployment certificate "
            "to authenticate and decrypt it. Expired alerts remain viewable."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        input_box = QGroupBox("🔐 Encrypted Telegram Alert")
        input_layout = QVBoxLayout(input_box)
        self.encrypted_alert_input = QTextEdit()
        self.encrypted_alert_input.setPlaceholderText(
            "Paste the Telegram alert here, beginning with\n"
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
        self.decrypt_sender.setTextFormat(Qt.TextFormat.PlainText)
        verification_layout.addRow("Status:", self.decrypt_status)
        verification_layout.addRow("Sent:", self.decrypt_sent_at)
        verification_layout.addRow("Expires:", self.decrypt_expires_at)
        verification_layout.addRow("Sender:", self.decrypt_sender)
        layout.addWidget(verification_box)

        message_box = QGroupBox("📡 Decrypted Telegram Alert")
        message_layout = QVBoxLayout(message_box)
        self.decrypted_message = QTextEdit()
        self.decrypted_message.setReadOnly(True)
        message_layout.addWidget(self.decrypted_message)
        layout.addWidget(message_box)

        self.decrypt_alert_btn.clicked.connect(self._decrypt_alert)
        self.clear_decrypt_btn.clicked.connect(self._clear_decrypt)
        return layout

    def on_panel_activated(self):
        """Focus the paste box after this cached panel enters the native stack."""
        self.encrypted_alert_input.ensurePolished()
        self.encrypted_alert_input.setFocus(Qt.FocusReason.OtherFocusReason)
        self.encrypted_alert_input.viewport().update()

    def _get_current_alert_keys(self):
        uid = (self.node or {}).get("universal_id")
        if not uid:
            raise RuntimeError("Current TelegramRelay agent has no universal_id.")

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
            self.decrypted_message.setPlainText(result["message"])

        except Exception as error:
            self._clear_decrypt_result()
            self.decrypt_status.setText("❌ Verification/decryption failed")
            self.decrypt_status.setStyleSheet("color: #ff5c5c;")
            emit_gui_exception_log("TelegramRelay._decrypt_alert", error)
            QMessageBox.warning(
                self,
                "Encrypted Telegram Alert Rejected",
                "Phoenix could not authenticate and decrypt this message.\n\n"
                f"{error}",
            )

    def _clear_decrypt_result(self):
        self.decrypt_sent_at.setText("—")
        self.decrypt_expires_at.setText("—")
        self.decrypt_sender.setText("—")
        self.decrypted_message.clear()

    def _clear_decrypt(self):
        self.encrypted_alert_input.clear()
        self._clear_decrypt_result()
        self.decrypt_status.setText("Not verified")
        self.decrypt_status.setStyleSheet("")
        self.encrypted_alert_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def _connect_signals(self):
        pass

    def _disconnect_signals(self):
        pass

    def get_panel_buttons(self):
        return [
            PanelButton(
                "📡",
                "TelegramRelay",
                lambda: self.session_window.show_specialty_panel(self),
            )
        ]
