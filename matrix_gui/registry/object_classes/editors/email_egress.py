# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
from PyQt6.QtWidgets import (
    QFormLayout, QLineEdit, QComboBox, QCheckBox, QLabel
)
from .base_editor import BaseEditor


class EmailEgress(BaseEditor):
    """
    Paired mailbox transport editor.

    Purpose:
      - Defines a single mailbox account that supports BOTH SMTP and IMAP
      - Ensures outgoing mail and inbox cleanup/monitoring belong to the same account
      - Injects one unified connection block into the agent deployment

    Notes:
      - This is NOT a generic SMTP-only editor
      - This is for mailbox-backed egress agents that need send + same-account inbox control
    """
    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn)

        default_channel_options = default_channel_options or ["payload.reception"]

        # ---------------------------------------------------------
        # Identity / behavior
        # ---------------------------------------------------------
        self.label = QLineEdit(self.generate_default_label())

        self.default_channel = QComboBox()
        self.default_channel.addItems(default_channel_options)

        self.default_payload_reception = QCheckBox("Primary Payload Reception Transport")
        self.default_payload_reception.setToolTip("Mark this connector as the default route for incoming payloads.")

        self.path_selector = QComboBox()
        self.path_selector.addItems([
            "config/email_egress",
            "config/mail",
            "config/smtp",
        ])

        # ---------------------------------------------------------
        # SMTP
        # ---------------------------------------------------------
        self.smtp_server = QLineEdit()
        self.smtp_port = QLineEdit()
        self.smtp_user = QLineEdit()
        self.smtp_pass = QLineEdit()
        self.smtp_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.smtp_to = QLineEdit()

        self.smtp_encryption = QComboBox()
        self.smtp_encryption.addItems(["SSL", "STARTTLS", "TLS", "None"])

        # ---------------------------------------------------------
        # Heartbeat SMTP
        # ---------------------------------------------------------
        self.heartbeat_smtp_user = QLineEdit()
        self.heartbeat_smtp_pass = QLineEdit()
        self.heartbeat_smtp_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.heartbeat_smtp_to = QLineEdit()

        # ---------------------------------------------------------
        # IMAP
        # ---------------------------------------------------------
        self.imap_server = QLineEdit()
        self.imap_port = QLineEdit()
        self.imap_user = QLineEdit()
        self.imap_pass = QLineEdit()
        self.imap_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.imap_folder = QLineEdit("INBOX")
        self.heartbeat_imap_folder = QLineEdit("INBOX.hb")

        # ---------------------------------------------------------
        # Mailbox behavior
        # ---------------------------------------------------------
        self.poll_interval = QLineEdit()
        self.poll_interval.setText("10")

        self.msg_retrieval_limit = QLineEdit()
        self.msg_retrieval_limit.setText("10")

        self.subject_prefix = QLineEdit("[MatrixSwarm]")
        self.from_filter = QLineEdit()

        self.cleanup_sent_copy = QCheckBox("Delete successfully processed mailbox copies")
        self.cleanup_sent_copy.setChecked(True)

        self.require_same_account = QCheckBox("Require recipient mailbox to match IMAP mailbox")
        self.require_same_account.setChecked(True)

        # ---------------------------------------------------------
        # Layout
        # ---------------------------------------------------------
        layout = QFormLayout(self)

        layout.addRow(QLabel("📮 Mailbox Identity"))
        layout.addRow("Label", self.label)
        layout.addRow("Directive Path", self.path_selector)
        layout.addRow("Serial", self.serial)

        #SMTP -> payload
        layout.addRow(QLabel("📤 SMTP"))
        layout.addRow("SMTP Server", self.smtp_server)
        layout.addRow("SMTP Port", self.smtp_port)
        layout.addRow("SMTP Username", self.smtp_user)
        layout.addRow("SMTP Password", self.smtp_pass)
        layout.addRow("Send To", self.smtp_to)
        layout.addRow("SMTP Encryption", self.smtp_encryption)

        #SMTP -> heartbeat
        layout.addRow(QLabel("💓 Heartbeat SMTP"))
        layout.addRow("Heartbeat SMTP Username", self.heartbeat_smtp_user)
        layout.addRow("Heartbeat SMTP Password", self.heartbeat_smtp_pass)
        layout.addRow("Heartbeat Send To", self.heartbeat_smtp_to)

        #IMAP <- payload
        layout.addRow(QLabel("📥 IMAP"))
        layout.addRow("IMAP Server", self.imap_server)
        layout.addRow("IMAP Port", self.imap_port)
        layout.addRow("IMAP Username", self.imap_user)
        layout.addRow("IMAP Password", self.imap_pass)
        layout.addRow("Folder", self.imap_folder)
        layout.addRow("Heartbeat Folder", self.heartbeat_imap_folder)

        layout.addRow(QLabel("⚙️ Mailbox Behavior"))
        layout.addRow("", self.default_payload_reception)
        layout.addRow("Channel", self.default_channel)

        layout.addRow("Poll Interval (sec)", self.poll_interval)
        layout.addRow("Message Retrieval Limit", self.msg_retrieval_limit)
        layout.addRow("Subject Prefix", self.subject_prefix)
        layout.addRow("From Filter", self.from_filter)
        layout.addRow("", self.cleanup_sent_copy)
        layout.addRow("", self.require_same_account)

    # ---------------------------------------------------------
    # Load existing data
    # ---------------------------------------------------------
    def on_load(self, data):
        path = data.get("node_directive_path", "config/email_egress")
        self.path_selector.setCurrentText(path)

        self.label.setText(data.get("label", ""))
        self.serial.setText(data.get("serial", ""))

        self.smtp_server.setText(data.get("smtp_server", ""))
        self.smtp_port.setText(str(data.get("smtp_port", "")))
        self.smtp_user.setText(data.get("smtp_username", ""))
        self.smtp_pass.setText(data.get("smtp_password", ""))
        self.smtp_to.setText(data.get("smtp_to", ""))
        self.smtp_encryption.setCurrentText(data.get("smtp_encryption", "SSL"))

        self.heartbeat_smtp_user.setText(
            data.get("heartbeat_smtp_username", data.get("smtp_username", ""))
        )
        self.heartbeat_smtp_pass.setText(
            data.get("heartbeat_smtp_password", data.get("smtp_password", ""))
        )
        self.heartbeat_smtp_to.setText(
            data.get("heartbeat_smtp_to", data.get("imap_username", ""))
        )

        self.imap_server.setText(data.get("imap_server", ""))
        self.imap_port.setText(str(data.get("imap_port", "")))
        self.imap_user.setText(data.get("imap_username", ""))
        self.imap_pass.setText(data.get("imap_password", ""))
        self.imap_folder.setText(data.get("imap_folder", "INBOX"))
        self.heartbeat_imap_folder.setText(data.get("heartbeat_imap_folder", "INBOX.hb"))

        self.poll_interval.setText(str(data.get("poll_interval", 10)))
        self.msg_retrieval_limit.setText(str(data.get("msg_retrieval_limit", 10)))
        self.subject_prefix.setText(data.get("subject_prefix", "[MatrixSwarm]"))
        self.from_filter.setText(data.get("from_filter", ""))

        self.cleanup_sent_copy.setChecked(bool(data.get("cleanup_sent_copy", True)))
        self.require_same_account.setChecked(bool(data.get("require_same_account", True)))
        self.default_payload_reception.setChecked(bool(data.get("default_payload_reception", False)))
        self.default_channel.setCurrentText(data.get("channel", ""))

    # ---------------------------------------------------------
    # Deployment injection
    # ---------------------------------------------------------
    def deploy_fields(self):
        return {
            "proto": "imap",
            "channel": self.default_channel.currentText(),
            "default_payload_reception": self.default_payload_reception.isChecked(),

            "payload_lane": {
                "direction": "swarm_to_phoenix",
                "smtp": {
                    "server": self.smtp_server.text().strip(),
                    "port": int(self.smtp_port.text() or 0),
                    "username": self.smtp_user.text().strip(),
                    "password": self.smtp_pass.text().strip(),
                    "to": self.smtp_to.text().strip(),
                    "encryption": self.smtp_encryption.currentText(),
                    "sensitive_fields": {"username": "1", "password": "1"},
                },
                "imap": {
                    "server": self.imap_server.text().strip(),
                    "port": int(self.imap_port.text() or 0),
                    "username": self.imap_user.text().strip(),
                    "password": self.imap_pass.text().strip(),
                    "folder": self.imap_folder.text().strip() or "INBOX",
                    "sensitive_fields": {"username": "1", "password": "1"},
                },
                "subject_prefix": self.subject_prefix.text().strip(),
                "from_filter": self.from_filter.text().strip(),
                "poll_interval": int(self.poll_interval.text() or 10),
                "msg_retrieval_limit": int(self.msg_retrieval_limit.text() or 10),
                "cleanup_sent_copy": self.cleanup_sent_copy.isChecked(),
            },

            "heartbeat_lane": {
                "direction": "phoenix_to_swarm",
                "enabled": True,
                "subject_prefix": "[MatrixSwarm-Heartbeat]",
                "interval_sec": 120,
                "timeout_sec": 300,
                "smtp": {
                    "server": self.smtp_server.text().strip(),
                    "port": int(self.smtp_port.text() or 0),
                    "username": self.heartbeat_smtp_user.text().strip(),
                    "password": self.heartbeat_smtp_pass.text().strip(),
                    "to": self.heartbeat_smtp_to.text().strip(),
                    "encryption": self.smtp_encryption.currentText(),
                    "sensitive_fields": {"username": "1", "password": "1"},
                },
                "imap": {
                    "server": self.imap_server.text().strip(),
                    "port": int(self.imap_port.text() or 0),
                    "username": self.imap_user.text().strip(),
                    "password": self.imap_pass.text().strip(),
                    "folder": self.heartbeat_imap_folder.text().strip() or "INBOX.hb",
                    "sensitive_fields": {"username": "1", "password": "1"},
                },
            },

            "require_same_account": self.require_same_account.isChecked(),
        }

    # ---------------------------------------------------------
    # Registry serialization
    # ---------------------------------------------------------
    def serialize(self):
        self._ensure_serial()
        return {
            "node_directive_path": self.path_selector.currentText().strip(),
            "serial": self.serial.text().strip(),
            "label": self.label.text().strip(),

            "smtp_server": self.smtp_server.text().strip(),
            "smtp_port": int(self.smtp_port.text() or 0),
            "smtp_username": self.smtp_user.text().strip(),
            "smtp_password": self.smtp_pass.text().strip(),
            "smtp_to": self.smtp_to.text().strip(),
            "smtp_encryption": self.smtp_encryption.currentText(),

            "heartbeat_smtp_username": self.heartbeat_smtp_user.text().strip(),
            "heartbeat_smtp_password": self.heartbeat_smtp_pass.text().strip(),
            "heartbeat_smtp_to": self.heartbeat_smtp_to.text().strip(),

            "imap_server": self.imap_server.text().strip(),
            "imap_port": int(self.imap_port.text() or 0),
            "imap_username": self.imap_user.text().strip(),
            "imap_password": self.imap_pass.text().strip(),
            "imap_folder": self.imap_folder.text().strip() or "INBOX",
            "heartbeat_imap_folder": self.heartbeat_imap_folder.text().strip() or "INBOX.hb",

            "poll_interval": int(self.poll_interval.text() or 10),
            "msg_retrieval_limit": int(self.msg_retrieval_limit.text() or 10),
            "subject_prefix": self.subject_prefix.text().strip(),
            "from_filter": self.from_filter.text().strip(),

            "cleanup_sent_copy": self.cleanup_sent_copy.isChecked(),
            "require_same_account": self.require_same_account.isChecked(),
            "channel": self.default_channel.currentText(),
            "default_payload_reception": self.default_payload_reception.isChecked(),
        }

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------
    def is_validated(self):
        # SMTP
        if not self.smtp_server.text().strip():
            return False, "SMTP Server required."
        if not self.smtp_port.text().isdigit():
            return False, "SMTP Port must be numeric."
        if not self.smtp_user.text().strip():
            return False, "SMTP Username required."
        if not self.smtp_pass.text().strip():
            return False, "SMTP Password required."
        if not self.smtp_to.text().strip():
            return False, "SMTP Send To required."
        if not self.heartbeat_smtp_user.text().strip():
            return False, "Heartbeat SMTP Username required."
        if not self.heartbeat_smtp_pass.text().strip():
            return False, "Heartbeat SMTP Password required."
        if not self.heartbeat_smtp_to.text().strip():
            return False, "Heartbeat Send To required."

        # IMAP
        if not self.imap_server.text().strip():
            return False, "IMAP Server required."
        if not self.imap_port.text().isdigit():
            return False, "IMAP Port must be numeric."
        if not self.imap_user.text().strip():
            return False, "IMAP Username required."
        if not self.imap_pass.text().strip():
            return False, "IMAP Password required."

        # Behavior
        if not self.poll_interval.text().isdigit():
            return False, "Poll Interval must be numeric."
        if not self.msg_retrieval_limit.text().isdigit():
            return False, "Message Retrieval Limit must be numeric."

        poll = int(self.poll_interval.text() or 0)
        limit = int(self.msg_retrieval_limit.text() or 0)

        if poll < 1:
            return False, "Poll Interval must be greater than 0."
        if limit < 1:
            return False, "Message Retrieval Limit must be greater than 0."

        # Same-account guard
        if self.require_same_account.isChecked():
            smtp_user = self.smtp_user.text().strip().lower()
            imap_user = self.imap_user.text().strip().lower()

            if smtp_user != imap_user:
                return False, "SMTP and IMAP usernames must match for paired mailbox mode."

        return True, ""