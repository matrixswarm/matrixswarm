# Authored by Daniel F MacDonald and ChatGPT-5 (“The Generals”)
from PyQt6.QtWidgets import QComboBox, QFormLayout, QLineEdit
from .base_editor import BaseEditor

class Telegram(BaseEditor):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn)

        self.default_channel = QComboBox()
        default_channel_options = default_channel_options or ["telegram", "outgoing.command"]
        self.default_channel.addItems(default_channel_options)

        self.path_selector = QComboBox()
        #node directive path - add as you see fit
        self.path_selector.addItems([
            "config/telegram",
        ])

        self.label = QLineEdit(self.generate_default_label())
        self.chat_id = QLineEdit()
        self.bot_token = QLineEdit()
        self.bot_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.note = QLineEdit()

        layout = QFormLayout(self)
        layout.addRow("Label", self.label)
        layout.addRow("Chat ID", self.chat_id)
        layout.addRow("Bot Token", self.bot_token)
        layout.addRow("Note", self.note)
        layout.addRow("Channel", self.default_channel)
        layout.addRow("Directive Path", self.path_selector)  # this is path in the json node where to put this
        layout.addRow("Serial", self.serial)

    def on_load(self, data):
        path = data.get("node_directive_path", "config/telegram")
        self.path_selector.setCurrentText(path)
        self.label.setText(data.get("label", ""))
        self.chat_id.setText(str(data.get("chat_id", "")))
        self.bot_token.setText(str(data.get("bot_token", "")))
        self.note.setText(data.get("note", ""))
        self.default_channel.setCurrentText(data.get("channel"))
        self.serial.setText(data.get("serial"))

    def deploy_fields(self):
        return {
            "chat_id": self.chat_id.text().strip(),
            "bot_token": self.bot_token.text().strip(),
            "channel": self.default_channel.currentText(),
            "sensitive_fields": {"bot_token": "1", "chat_id": "1", "channel": "1"},
        }

    def serialize(self):
        return {
            "node_directive_path": self.path_selector.currentText().strip(),
            "label": self.label.text().strip(),
            "chat_id": self.chat_id.text().strip(),
            "bot_token": self.bot_token.text().strip(),
            "note": self.note.text().strip(),
            "channel": self.default_channel.currentText(),
            "serial": self.serial.text().strip(),
        }

    def is_validated(self):
        if not self.chat_id.text().strip():
            return False, "Chat ID is required."
        if not self.bot_token.text().strip():
            return False, "Bot Token is required."
        # Validate protocol
        if not self.serial.text().strip():
            return False, "Serial is required."
        if self.default_channel.currentText().strip() == "":
            return False, "Channel is required."
        return True, ""
