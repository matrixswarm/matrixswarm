# Authored by Daniel F MacDonald and ChatGPT-5.1 (“The Generals”)
from PyQt6.QtWidgets import QFormLayout, QLineEdit, QComboBox
from .base_editor import BaseEditor

class Pop3(BaseEditor):
    """Incoming POP3 editor."""

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn)

        self.default_channel = QComboBox()
        default_channel_options = default_channel_options or ["receive.email", "payload.reception"]
        self.default_channel.addItems(default_channel_options)

        self.label = QLineEdit(self.generate_default_label())
        self.in_server = QLineEdit()
        self.in_port = QLineEdit()
        self.in_user = QLineEdit()
        self.in_pass = QLineEdit()
        self.in_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.in_encryption = QComboBox()
        self.in_encryption.addItems(["SSL", "STARTTLS", "TLS", "None"])

        self.path_selector = QComboBox()
        #node directive path - add as you see fit
        self.path_selector.addItems([
            "config/pop3",  # default
            #"config/imap_bk",
            #"config/imap_legacy",
            #"config/mail"
        ])

        layout = QFormLayout(self)
        layout.addRow("Label", self.label)
        layout.addRow("Server", self.in_server)
        layout.addRow("Port", self.in_port)
        layout.addRow("Username", self.in_user)
        layout.addRow("Password", self.in_pass)
        layout.addRow("Encryption", self.in_encryption)
        layout.addRow("Channel", self.default_channel)
        layout.addRow("Directive Path", self.path_selector)  #  this is json node path where the agent's config is written
        layout.addRow("Serial", self.serial)

    def deploy_fields(self):
        return {
            "incoming_server": self.in_server.text().strip(),
            "incoming_port": int(self.in_port.text() or 0),
            "incoming_username": self.in_user.text().strip(),
            "incoming_password": self.in_pass.text().strip(),
            "incoming_encryption": self.in_encryption.currentText(),
            "channel": self.default_channel.currentText(),
            "sensitive_fields": {"incoming_username": "1", "incoming_password": "1"},
        }

    def on_load(self, data):
        path = data.get("node_directive_path", "config/pop3")
        self.path_selector.setCurrentText(path)
        self.label.setText(data.get("label", ""))
        self.serial.setText(data.get("serial", ""))
        self.in_server.setText(data.get("incoming_server", ""))
        self.in_port.setText(str(data.get("incoming_port", "")))
        self.in_user.setText(data.get("incoming_username", ""))
        self.in_pass.setText(data.get("incoming_password", ""))
        self.in_encryption.setCurrentText(data.get("incoming_encryption", "SSL"))
        self.default_channel.setCurrentText(data.get("channel", ""))

    def serialize(self):
        self._ensure_serial()
        return {
            "node_directive_path": self.path_selector.currentText().strip(),
            "serial": self.serial.text().strip(),
            "label": self.label.text().strip(),
            "incoming_server": self.in_server.text().strip(),
            "incoming_port": int(self.in_port.text() or 0),
            "incoming_username": self.in_user.text().strip(),
            "incoming_password": self.in_pass.text().strip(),
            "incoming_encryption": self.in_encryption.currentText(),
            "channel": self.default_channel.currentText(),
        }

    def is_validated(self):
        if not self.in_server.text().strip():
            return False, "POP3 Server required."
        if not self.in_port.text().isdigit():
            return False, "POP3 Port must be numeric."
        return True, ""
