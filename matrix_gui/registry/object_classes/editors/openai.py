# Authored by Daniel F MacDonald and ChatGPT-5 (“The Generals”)
from PyQt6.QtWidgets import QComboBox, QFormLayout, QLineEdit
from .base_editor import BaseEditor

class OpenAI(BaseEditor):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn)

        self.label = QLineEdit(self.generate_default_label())
        self.default_channel = QComboBox()

        default_channel_options = default_channel_options or ["oracle"]
        self.default_channel.addItems(default_channel_options)

        self.path_selector = QComboBox()
        #node directive path - add as you see fit
        self.path_selector.addItems([
            "config/openai",  # default
            #"config/imap_bk",
            #"config/imap_legacy",
            #"config/mail"
        ])

        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.note = QLineEdit()

        layout = QFormLayout(self)
        layout.addRow("Label", self.label)
        layout.addRow("API Key", self.api_key)
        layout.addRow("Note", self.note)
        layout.addRow("Channel", self.default_channel)
        layout.addRow("Directive Path", self.path_selector)  #  this is json node path where the agent's config is written
        layout.addRow("Serial", self.serial)

    def deploy_fields(self):
        return {
            "api_key": self.api_key.text().strip(),
            "channel": self.default_channel.currentText(),
            "sensitive_fields": {"api_key": "1"},
        }

    def on_load(self, data):
        path = data.get("node_directive_path", "config/openai")
        self.path_selector.setCurrentText(path)
        self.label.setText(data.get("label", ""))
        self.api_key.setText(data.get("api_key", ""))
        self.note.setText(data.get("note", ""))
        self.default_channel.setCurrentText(data.get("channel"))
        self.serial.setText(data.get("serial"))

    def serialize(self):
        return {
            "node_directive_path": self.path_selector.currentText().strip(),
            "label": self.label.text().strip(),
            "api_key": self.api_key.text().strip(),
            "note": self.note.text().strip(),
            "channel": self.default_channel.currentText(),
            "serial": self.serial.text().strip(),
        }

    def is_validated(self):
        if not self.api_key.text().strip():
            return False, "API key required."
        if not self.serial.text().strip():
            return False, "Serial is required."

        if self.default_channel.currentText().strip() == "":
            return False, "Channel is required."

        return True, ""
