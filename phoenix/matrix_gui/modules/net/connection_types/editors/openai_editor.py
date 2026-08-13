from PyQt6.QtWidgets import QComboBox, QFormLayout, QLineEdit
from .base_editor import ConnectionEditorInterface

class OpenAIConnectionEditor(ConnectionEditorInterface):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn, default_channel_options)

        self.proto = QLineEdit()
        self.serial = QLineEdit()

        # Lock fields from editing (inherited behavior)
        self._lock_proto_and_serial(self.proto, self.serial)

        self.label = QLineEdit()
        self.default_channel = QComboBox()
        self.default_channel.addItems(default_channel_options)

        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.note = QLineEdit()

        layout = QFormLayout(self)
        layout.addRow("Protocol", self.proto)
        layout.addRow("Label", self.label)
        layout.addRow("API Key", self.api_key)
        layout.addRow("Note", self.note)
        layout.addRow("Default Channel", self.default_channel)
        layout.addRow("Serial", self.serial)

    def on_load(self, data):
        self.proto.setText(data.get("proto", "openai"))
        self.label.setText(data.get("label", ""))
        self.api_key.setText(data.get("api_key", ""))
        self.note.setText(data.get("note", ""))
        self.default_channel.setCurrentText(data.get("default_channel"))
        self.serial.setText(data.get("serial"))

    def serialize(self):
        return {
            "proto": "openai",
            "label": self.label.text().strip(),
            "api_key": self.api_key.text().strip(),
            "note": self.note.text().strip(),
            "default_channel": self.default_channel.currentText(),
            "serial": self.serial.text().strip(),
        }

    def validate(self):
        if not self.api_key.text().strip():
            return False, "API key required."
        if not self.serial.text().strip():
            return False, "Serial is required."

        if self.default_channel.currentText().strip() == "":
            return False, "Default channel is required."

        return True, ""
