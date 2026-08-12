from PyQt6.QtWidgets import QComboBox, QFormLayout, QLineEdit
from .base_editor import ConnectionEditorInterface

class SlackConnectionEditor(ConnectionEditorInterface):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn, default_channel_options)

        self.proto = QLineEdit()
        self.serial = QLineEdit()

        # Lock fields from editing (inherited behavior)
        self._lock_proto_and_serial(self.proto, self.serial)
        self.default_channel = QComboBox()
        self.default_channel.addItems(default_channel_options)


        self.label = QLineEdit()
        self.webhook_url = QLineEdit()
        self.note = QLineEdit()
        layout = QFormLayout(self)
        layout.addRow("Protocol", self.proto)
        layout.addRow("Label", self.label)
        layout.addRow("Webhook URL", self.webhook_url)
        layout.addRow("Note", self.note)
        layout.addRow("Default Channel", self.default_channel)
        layout.addRow("Serial", self.serial)

    def on_load(self, data):
        self.proto.setText(data.get("proto", "slack"))
        self.label.setText(data.get("label", ""))
        self.webhook_url.setText(data.get("webhook_url", ""))
        self.note.setText(data.get("note", ""))
        self.default_channel.setCurrentText(data.get("default_channel"))
        self.serial.setText(data.get("serial"))

    def serialize(self):
        return {
            "proto": "slack",
            "label": self.label.text().strip(),
            "webhook_url": self.webhook_url.text().strip(),
            "note": self.note.text().strip(),
            "default_channel": self.default_channel.currentText(),
            "serial": self.serial.text().strip(),
        }

    def validate(self):
        if not self.webhook_url.text().strip():
            return False, "Webhook URL required."

        if not self.webhook_url.text().startswith("http"):
            return False, "Webhook URL must begin with http/https."
        if not self.serial.text().strip():
            return False, "Serial is required."
        if self.default_channel.currentText().strip() == "":
            return False, "Default channel is required."
        return True, ""
