# Authored by Commander & ChatGPT-5.1 — MySQL Editor
from PyQt6.QtWidgets import QFormLayout, QLineEdit, QComboBox
from .base_editor import ConnectionEditorInterface


class MySQLConnectionEditor(ConnectionEditorInterface):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn, default_channel_options)

        self.proto = QLineEdit()
        self.serial = QLineEdit()
        self.label = QLineEdit()
        self.default_channel = QComboBox()
        self.default_channel.addItems(default_channel_options or [])

        # MySQL core fields
        self.host = QLineEdit()
        self.port = QLineEdit()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.database = QLineEdit()

        # Lock proto/serial
        self.proto.setText("mysql")
        self._lock_proto_and_serial(self.proto, self.serial)

        layout = QFormLayout(self)
        layout.addRow("Protocol", self.proto)
        layout.addRow("Label", self.label)
        layout.addRow("Host", self.host)
        layout.addRow("Port", self.port)
        layout.addRow("Username", self.username)
        layout.addRow("Password", self.password)
        layout.addRow("Database", self.database)
        layout.addRow("Default Channel", self.default_channel)
        layout.addRow("Serial", self.serial)

    # ------------------------------
    def on_load(self, data):
        self.proto.setText("mysql")
        self.serial.setText(data.get("serial", ""))

        self.label.setText(data.get("label", ""))
        self.default_channel.setCurrentText(data.get("default_channel", ""))

        self.host.setText(data.get("host", ""))
        self.port.setText(str(data.get("port", 3306)))
        self.username.setText(data.get("username", ""))
        self.password.setText(data.get("password", ""))
        self.database.setText(data.get("database", ""))

    # ------------------------------
    def serialize(self):
        self._ensure_serial()

        return {
            "proto": "mysql",
            "serial": self.serial.text().strip(),
            "label": self.label.text().strip(),
            "default_channel": self.default_channel.currentText(),

            "host": self.host.text().strip(),
            "port": int(self.port.text() or 3306),
            "username": self.username.text().strip(),
            "password": self.password.text().strip(),
            "database": self.database.text().strip(),
        }

    # ------------------------------
    def validate(self):
        if not self.label.text().strip():
            return False, "Label is required."

        if not self.host.text().strip():
            return False, "Host is required."

        if not self.port.text().isdigit():
            return False, "Port must be numeric."

        if not self.username.text().strip():
            return False, "Username required."

        if not self.database.text().strip():
            return False, "Database name required."

        if self.default_channel.currentText().strip() == "":
            return False, "Default channel is required."

        return True, ""
