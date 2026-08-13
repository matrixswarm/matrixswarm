# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
from PyQt6.QtWidgets import QComboBox, QFormLayout, QLineEdit
from .base_editor import ConnectionEditorInterface
from matrix_gui.core.class_lib.validation.network.ip_utils import IPUtils
from matrix_gui.core.class_lib.validation.network.protocol_utils import ProtocolUtils
from matrix_gui.core.class_lib.validation.network.port_utils import PortUtils
class WSSConnectionEditor(ConnectionEditorInterface):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn, default_channel_options)

        self.proto = QLineEdit()
        self.serial = QLineEdit()

        # Lock fields from editing (inherited behavior)
        self._lock_proto_and_serial(self.proto, self.serial)
        self.default_channel = QComboBox()
        self.default_channel.addItems(default_channel_options)

        self.label = QLineEdit()
        self.host = QLineEdit()
        self.port = QLineEdit()
        self.note = QLineEdit()
        self.allowlist_ips = QLineEdit()

        layout = QFormLayout(self)
        layout.addRow("Protocol", self.proto)
        layout.addRow("Label", self.label)
        layout.addRow("Host", self.host)
        layout.addRow("Port", self.port)
        layout.addRow("Note", self.note)
        layout.addRow("Allowlist IPs", self.allowlist_ips)
        layout.addRow("Default Channel", self.default_channel)
        layout.addRow("Serial", self.serial)

        # Always pre-set correct proto for this editor
        self.proto.setText("wss")

    def on_load(self, data):
        self.proto.setText(data.get("proto", "https"))
        self.label.setText(data.get("label", ""))
        self.host.setText(data.get("host"))
        self.port.setText(str(data.get("port")))
        self.note.setText(data.get("note", ""))
        self.allowlist_ips.setText(", ".join(data.get("allowlist_ips", [])))
        self.default_channel.setCurrentText(data.get("default_channel", ""))
        self.serial.setText(data.get("serial"))

    def serialize(self):
        return {
            "proto": "wss",
            "label": self.label.text().strip(),
            "host": self.host.text().strip(),
            "port": int(self.port.text() or 0),
            "note": self.note.text().strip(),
            "allowlist_ips": [
                ip.strip() for ip in self.allowlist_ips.text().split(",") if ip.strip()
            ],
            "default_channel": self.default_channel.currentText(),
            "serial": self.serial.text().strip(),
        }

    def validate(self):
        """
        Validate the current state of the form fields.

        Returns:
            tuple: A tuple containing:
                - bool: True if the fields are valid, False otherwise.
                - str: An error message if validation fails, otherwise an empty string.
        """
        # Validate host
        if not self.host.text().strip():
            return False, "Host is required."

        # Validate port
        if not self.port.text().isdigit():
            return False, "Port must be numeric."
        if not PortUtils.validate_port(self.port.text()):
            return False, "Port must be a valid number between 1 and 65535."

        # Validate protocol
        if not ProtocolUtils.validate_protocol(self.proto.text(), "wss"):
            return False, "Protocol must be 'https'."

        # Validate allowlist_ips
        allowlist_ips = self.allowlist_ips.text()
        if allowlist_ips:
            for ip in allowlist_ips.split(","):
                ip = ip.strip()
                if not ip:
                    continue
                if not IPUtils.validate_ip(ip):
                    return False, f"Invalid IP address in allowlist: '{ip}'."

        # Validate serial
        if not self.serial.text().strip():
            return False, "Serial is required."

        if self.default_channel.currentText().strip() == "":
            return False, "Default channel is required."

        # All fields are valid
        return True, ""
