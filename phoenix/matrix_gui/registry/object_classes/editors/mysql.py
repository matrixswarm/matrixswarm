# Authored by Commander & ChatGPT-5.1 — MySQL Editor
from PyQt6.QtWidgets import QFormLayout, QLineEdit, QComboBox
from .base_editor import BaseEditor


class MYSQL(BaseEditor):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn)

        self.label = QLineEdit(self.generate_default_label())

        self.default_channel = QComboBox()
        default_channel_options = default_channel_options or ["mysql"]
        self.default_channel.addItems(default_channel_options)

        self.path_selector = QComboBox()
        # node directive path - add as you see fit
        self.path_selector.addItems([
            "config/mysql",  # default
            # "config/mysql_bk",
        ])


        # MySQL core fields
        self.host = QLineEdit()
        self.port = QLineEdit()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.database = QLineEdit()

        layout = QFormLayout(self)
        layout.addRow("Label", self.label)
        layout.addRow("Host", self.host)
        layout.addRow("Port", self.port or 3306)
        layout.addRow("Username", self.username)
        layout.addRow("Password", self.password)
        layout.addRow("Database", self.database)
        layout.addRow("Channel", self.default_channel)
        layout.addRow("Directive Path", self.path_selector)  #  this is json node path where the agent's config is written
        layout.addRow("Serial", self.serial)

    def get_directory_path(self):
        if self.label.text().lower().strip() == "mysql":
            return ["config", "mysql_bk"]
        return ["config","mysql"]

    def deploy_fields(self):  # :contentReference[oaicite:1]{index=1}
        return {
            "host": self.host.text().strip(),
            "port": int(self.port.text() or 3306),
            "username": self.username.text().strip(),
            "password": self.password.text().strip(),
            "database": self.database.text().strip(),
            "sensitive_fields": {"password": "1"},
        }

    def on_load(self, data):
        path = data.get("node_directive_path", "config/mysql")
        self.path_selector.setCurrentText(path)
        self.serial.setText(data.get("serial", ""))

        self.label.setText(data.get("label", ""))
        self.default_channel.setCurrentText(data.get("channel", ""))

        self.host.setText(data.get("host", ""))
        self.port.setText(str(data.get("port", 3306)))
        self.username.setText(data.get("username", ""))
        self.password.setText(data.get("password", ""))
        self.database.setText(data.get("database", ""))

    # ------------------------------
    def serialize(self):
        self._ensure_serial()

        return {
            "node_directive_path": self.path_selector.currentText().strip(),
            "serial": self.serial.text().strip(),
            "label": self.label.text().strip(),
            "channel": self.default_channel.currentText(),

            "host": self.host.text().strip(),
            "port": int(self.port.text() or 3306),
            "username": self.username.text().strip(),
            "password": self.password.text().strip(),
            "database": self.database.text().strip(),
        }

    # ------------------------------
    def is_validated(self):
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
            return False, "Channel is required."

        return True, ""
