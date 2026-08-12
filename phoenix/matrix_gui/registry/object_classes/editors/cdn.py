# Authored by Daniel F MacDonald and ChatGPT-5 (“The Generals”)
from PyQt6.QtWidgets import (
    QFormLayout, QLineEdit, QTextEdit, QComboBox,
    QPushButton, QMessageBox
)
import paramiko, io
from Crypto.PublicKey import RSA
from .base_editor import BaseEditor

class CDN(BaseEditor):
    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent)

        self.label = QLineEdit(self.generate_default_label())
        self.host = QLineEdit()
        self.port = QLineEdit("22")
        self.username = QLineEdit()
        self.remote_path = QLineEdit("/public/")
        self.auth_type = QComboBox()
        self.auth_type.addItems(["password", "private_key", "api_key"])
        self.path_selector = QComboBox()
        # node directive path - add as you see fit
        self.path_selector.addItems([
            "config/cdn",  # default
            # "config/cdn_bk",
            # "config/cdn_legacy",
        ])

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)

        self.private_key = QTextEdit()
        self.public_key = QTextEdit()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)

        # Buttons
        self.gen_btn = QPushButton("🗝️ Generate Key Pair")
        self.test_btn = QPushButton("🔌 Test Connection")
        self.view_pub_btn = QPushButton("👁 View Public Key")

        self.gen_btn.clicked.connect(self._generate_keypair)
        self.test_btn.clicked.connect(self._test_connection)
        self.view_pub_btn.clicked.connect(self._view_pubkey)

        layout = QFormLayout(self)
        layout.addRow("Label", self.label)
        layout.addRow("Host", self.host)
        layout.addRow("Port", self.port)
        layout.addRow("Username", self.username)
        layout.addRow("Auth Type", self.auth_type)
        layout.addRow("Password", self.password)
        layout.addRow("Private Key", self.private_key)
        layout.addRow("Public Key", self.public_key)
        layout.addRow("API Key", self.api_key)
        layout.addRow("Remote Path", self.remote_path)
        layout.addRow(self.gen_btn)
        layout.addRow(self.test_btn)
        layout.addRow(self.view_pub_btn)

        layout.addRow("Serial", self.serial)

    def deploy_fields(self):
        data = {
            "host": self.host.text().strip(),
            "port": int(self.port.text() or 22),
            "username": self.username.text().strip(),
            "auth_type": self.auth_type.currentText(),
            "remote_path": self.remote_path.text().strip(),
        }

        mode = self.auth_type.currentText()
        if mode == "password":
            data["password"] = self.password.text().strip()
        elif mode == "private_key":
            data["private_key"] = self.private_key.toPlainText().strip()
            data["private_key_passphrase"] = ""  # optional
        elif mode == "api_key":
            data["api_key"] = self.api_key.text().strip()

        return data

    def _generate_keypair(self):
        key = RSA.generate(2048)
        priv = key.export_key("PEM").decode()
        pub = key.publickey().export_key("PEM").decode()
        self.private_key.setPlainText(priv)
        self.public_key.setPlainText(pub)
        QMessageBox.information(self, "Key Pair Generated",
                                "New RSA key pair created and loaded into the editor.")

    def _view_pubkey(self):
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Public Key")
        dlg.setText(self.public_key.toPlainText())
        dlg.exec()

    def _test_connection(self):
        host = self.host.text().strip()
        user = self.username.text().strip()
        auth = self.auth_type.currentText()
        try:
            if auth == "password":
                client = paramiko.Transport((host, int(self.port.text())))
                client.connect(username=user, password=self.password.text())
                client.close()
            elif auth == "private_key":
                key = paramiko.RSAKey.from_private_key(io.StringIO(self.private_key.toPlainText()))
                client = paramiko.Transport((host, int(self.port.text())))
                client.connect(username=user, pkey=key)
                client.close()
            QMessageBox.information(self, "Connection OK", "CDN connection succeeded.")
        except Exception as e:
            QMessageBox.critical(self, "Connection Failed", str(e))

    # ----------------------------------------------------------
    def on_load(self, data):
        """Populate fields from stored CDN connection data."""
        path = data.get("node_directive_path", "config/imap")
        self.path_selector.setCurrentText(path)
        self.serial.setText(data.get("serial", ""))
        self.label.setText(data.get("label", ""))
        self.host.setText(str(data.get("host", "")))
        self.port.setText(str(data.get("port", "")))
        self.username.setText(str(data.get("username", "")))
        self.remote_path.setText(str(data.get("remote_path", "")))

        mode = data.get("auth_type", "password")
        self.auth_type.setCurrentText(mode)

        self.password.setText(str(data.get("password", "")))
        self.private_key.setPlainText(str(data.get("private_key", "")))
        self.public_key.setPlainText(str(data.get("public_key", "")))
        self.api_key.setText(str(data.get("api_key", "")))

    def serialize(self):
        """Return a dictionary suitable for vault storage."""
        self._ensure_serial()
        out = {
            "node_directive_path": self.path_selector.currentText().strip(),
            "serial": self.serial.text().strip(),
            "label": self.label.text().strip(),
            "host": self.host.text().strip(),
            "port": int(self.port.text() or 22),
            "username": self.username.text().strip(),
            "auth_type": self.auth_type.currentText(),
            "remote_path": self.remote_path.text().strip(),
            "password": self.password.text().strip(),
            "private_key": self.private_key.toPlainText().strip(),
            "public_key": self.public_key.toPlainText().strip(),
            "api_key": self.api_key.text().strip(),
        }
        return out

    def is_validated(self):
        """Basic field validation before save."""
        ok, msg = self._require_serial()
        if not ok:
            return ok, msg

        if not self.label.text().strip():
            return False, "Label is required."
        if not self.host.text().strip():
            return False, "Host is required."

        mode = self.auth_type.currentText()
        if mode == "password" and not self.password.text().strip():
            return False, "Password required for password auth."
        if mode == "private_key" and not self.private_key.toPlainText().strip():
            return False, "Private key required."
        if mode == "api_key" and not self.api_key.text().strip():
            return False, "API key required for API auth."

        return True, ""