from PyQt6.QtWidgets import QFormLayout, QLineEdit, QComboBox
from .base_editor import ConnectionEditorInterface

class DiscordConnectionEditor(ConnectionEditorInterface):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn, default_channel_options)

        self.proto = QLineEdit()
        self.serial = QLineEdit()

        # Lock fields from editing (inherited behavior)
        self._lock_proto_and_serial(self.proto, self.serial)

        self.label = QLineEdit()
        self.default_channel = QComboBox()
        self.default_channel.addItems(default_channel_options)
        self.channel_id = QLineEdit()
        self.bot_token = QLineEdit()
        self.bot_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.note = QLineEdit()

        layout = QFormLayout(self)
        layout.addRow("Protocol", self.proto)
        layout.addRow("Label", self.label)
        layout.addRow("Channel ID", self.channel_id)
        layout.addRow("Bot Token", self.bot_token)
        layout.addRow("Note", self.note)
        layout.addRow("Default Channel", self.default_channel)
        layout.addRow("Serial", self.serial)

    def on_load(self, data):
        self.label.setText(data.get("label", ""))
        self.proto.setText(data.get("proto", "discord"))
        self.channel_id.setText(str(data.get("channel_id", "")))
        self.bot_token.setText(data.get("bot_token", ""))
        self.note.setText(data.get("note", ""))
        self.default_channel.setCurrentText(data.get("default_channel"))
        self.serial.setText(data.get("serial"))

    def serialize(self):
        return {
            "proto": "discord",
            "label": self.label.text().strip(),
            "channel_id": self.channel_id.text().strip(),
            "bot_token": self.bot_token.text().strip(),
            "note": self.note.text().strip(),
            "default_channel": self.default_channel.currentText(),
            "serial": self.serial.text().strip(),
        }

    def validate(self):
        if not self.channel_id.text().strip():
            return False, "Channel ID is required."
        if not self.bot_token.text().strip():
            return False, "Bot Token is required."
        if not self.serial.text().strip():
            return False, "Serial is required."

        if self.default_channel.currentText().strip() == "":
            return False, "Default channel is required."
        return True, ""
