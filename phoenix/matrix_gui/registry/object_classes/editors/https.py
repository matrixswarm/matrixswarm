# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
from PyQt6.QtWidgets import QComboBox, QFormLayout, QLineEdit, QCheckBox
from .base_editor import BaseEditor
from matrix_gui.core.class_lib.validation.network.ip_utils import IPUtils
from matrix_gui.core.class_lib.validation.network.port_utils import PortUtils
class HTTPS(BaseEditor):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn)

        # Lock fields from editing (inherited behavior)
        self.default_channel = QComboBox()
        default_channel_options = default_channel_options or ["outgoing.command"]
        self.default_channel.addItems(default_channel_options)
        self.default_outgoing = QCheckBox("Primary Outgoing Transport")
        self.default_outgoing.setToolTip("Mark this connector as the default route for outgoing commands.")

        self.path_selector = QComboBox()
        # node directive path - add as you see fit - I'll fix this in the future - add config/https
        self.path_selector.addItems([
            "config", #default
            #"config/https",
            # "config/https_bk",
            # "config/https_legacy",
        ])

        self.label = QLineEdit(self.generate_default_label())
        self.host = QLineEdit()
        self.port = QLineEdit()
        self.note = QLineEdit()
        self.allowlist_ips = QLineEdit()

        layout = QFormLayout(self)
        layout.addRow("Label", self.label)
        layout.addRow("Host", self.host)
        layout.addRow("Port", self.port or 443)
        layout.addRow("Note", self.note)
        layout.addRow("Allowlist IPs", self.allowlist_ips)
        layout.addRow("", self.default_outgoing)
        layout.addRow("Channel", self.default_channel)
        layout.addRow("Directive Path", self.path_selector)  #  this is json node path where the agent's config is written
        layout.addRow("Serial", self.serial)

    def on_load(self, data):
        path = data.get("node_directive_path", "config")
        self.path_selector.setCurrentText(path)
        self.label.setText(data.get("label", ""))
        self.host.setText(data.get("host"))
        self.port.setText(str(data.get("port") or 443))
        self.note.setText(data.get("note", ""))
        self.allowlist_ips.setText(", ".join(data.get("allowlist_ips", [])))
        self.default_outgoing.setChecked(bool(data.get("default_outgoing", False)))
        self.default_channel.setCurrentText(data.get("channel"))
        self.serial.setText(data.get("serial"))

    def deploy_fields(self):
        return {
            "proto": "https",
            "default": True,
            "host": self.host.text().strip(),
            "port": int(self.port.text() or 443),
            "allowlist_ips": [
                ip.strip() for ip in self.allowlist_ips.text().split(",") if ip.strip()
            ],
            "channel": self.default_channel.currentText(),
            "default_outgoing": self.default_outgoing.isChecked(),
        }

    def serialize(self) -> dict:
        # Ensure serial exists (auto-generate for NEW)
        self._ensure_serial()

        return {
            "node_directive_path": self.path_selector.currentText().strip(),
            "label": self.label.text().strip(),
            "host": self.host.text().strip(),
            "port": int(self.port.text() or 0),
            "note": self.note.text().strip(),
            "allowlist_ips": [
                ip.strip() for ip in self.allowlist_ips.text().split(",") if ip.strip()
            ],
            "channel": self.default_channel.currentText(),
            "default_outgoing": self.default_outgoing.isChecked(),
            "serial": self.serial.text().strip(),
        }

    def is_connection(self)-> bool:
        """
        Is this a connection? Have Ip
        """
        return True

    def is_validated(self):
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
            return False, "Channel is required."

        # All fields are valid
        return True, ""
