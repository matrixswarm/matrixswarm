from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtWidgets import (
    QFormLayout, QLineEdit, QComboBox,
    QTextEdit, QPushButton
)
from .base_editor import ConnectionEditorInterface
from matrix_gui.modules.railgun.ssh_support import (
    connect_ssh_profile,
    load_private_key,
    normalize_fingerprint,
    probe_ssh_host_fingerprint,
)


class SSHConnectionEditor(ConnectionEditorInterface):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn, default_channel_options)

        # Identity
        self.proto = QLineEdit()
        self.serial = QLineEdit()
        self.label = QLineEdit()
        self.default_channel = QComboBox()
        self.default_channel.addItems(default_channel_options or [])

        self.proto.setText("ssh")
        self._lock_proto_and_serial(self.proto, self.serial)

        # SSH Core
        self.host = QLineEdit()
        self.port = QLineEdit()
        self.username = QLineEdit()

        # Authentication
        self.auth_type = QComboBox()
        self.auth_type.addItems(["password", "private_key", "agent"])

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)

        self.private_key = QTextEdit()
        self.private_key.setPlaceholderText("-----BEGIN OPENSSH PRIVATE KEY-----")

        self.passphrase = QLineEdit()
        self.passphrase.setEchoMode(QLineEdit.EchoMode.Password)

        # Security
        self.fingerprint = QLineEdit()
        self.fingerprint.setPlaceholderText("SHA256:xxxxxx (host key fingerprint)")

        # Layout
        layout = QFormLayout(self)
        layout.addRow("Protocol", self.proto)
        layout.addRow("Label", self.label)
        layout.addRow("Host", self.host)
        layout.addRow("Port", self.port)
        layout.addRow("Username", self.username)
        layout.addRow("Auth Type", self.auth_type)
        layout.addRow("Password", self.password)
        layout.addRow("Private Key", self.private_key)
        layout.addRow("Passphrase", self.passphrase)
        layout.addRow("Trusted Fingerprint", self.fingerprint)
        layout.addRow("Default Channel", self.default_channel)
        layout.addRow("Serial", self.serial)

        #test connection
        self.test_btn = QPushButton("🔌 Test Connection")
        self.test_btn.clicked.connect(self._test_connection)
        layout.addRow(self.test_btn)

        # Visibility rules
        self.auth_type.currentTextChanged.connect(self._render_auth_mode)
        self._render_auth_mode(self.auth_type.currentText())

    # --------------------------
    def _render_auth_mode(self, mode):
        """Show/hide fields depending on auth method."""
        self.password.setVisible(mode == "password")
        self.private_key.setVisible(mode == "private_key")
        self.passphrase.setVisible(mode == "private_key")

    # --------------------------
    def on_load(self, data):
        self.proto.setText("ssh")
        self.serial.setText(data.get("serial", ""))
        self.label.setText(data.get("label", ""))

        self.host.setText(str(data.get("host", "")))
        self.port.setText(str(data.get("port", "")))
        self.username.setText(str(data.get("username", "")))

        mode = data.get("auth_type", "password")
        self.auth_type.setCurrentText(mode)

        self.password.setText(str(data.get("password", "")))
        self.private_key.setText(str(data.get("private_key", "")))
        self.passphrase.setText(str(data.get("private_key_passphrase", "")))

        self.fingerprint.setText(str(data.get("trusted_host_fingerprint", "")))

        self.default_channel.setCurrentText(data.get("default_channel", ""))

        self._render_auth_mode(mode)

    # --------------------------
    def serialize(self):
        self._ensure_serial()

        out = {
            "proto": "ssh",
            "serial": self.serial.text().strip(),
            "label": self.label.text().strip(),
            "default_channel": self.default_channel.currentText(),
            "host": self.host.text().strip(),
            "port": int(self.port.text() or 22),
            "username": self.username.text().strip(),
            "auth_type": self.auth_type.currentText(),
            "trusted_host_fingerprint": self.fingerprint.text().strip(),
        }

        if out["auth_type"] == "password":
            out["password"] = self.password.text().strip()
            out["private_key"] = "None"
            out["private_key_passphrase"] = "None"


        elif out["auth_type"] == "private_key":
            out["private_key"] = self.private_key.toPlainText().strip()
            out["private_key_passphrase"] = self.passphrase.text().strip() or "None"
            out["password"] = self.password.text().strip() or "None"

        return out

    # --------------------------
    def validate(self):
        ok, msg = self._require_proto_and_serial()
        if not ok:
            return ok, msg

        if not self.label.text().strip():
            return False, "Label is required."

        if not self.host.text().strip():
            return False, "Host is required."

        if not self.port.text().isdigit():
            return False, "Port must be numeric."

        method = self.auth_type.currentText()
        if method == "password" and not self.password.text().strip():
            return False, "Password required for password auth."

        if method == "private_key" and not self.private_key.toPlainText().strip():
            return False, "Private key required."

        if method == "private_key":
            try:
                load_private_key(
                    self.private_key.toPlainText(),
                    self.passphrase.text(),
                )
            except ValueError as exc:
                return False, str(exc)

        if not self.fingerprint.text().strip():
            return False, "Trusted SHA256 host fingerprint is required."

        return True, ""

    def _connection_snapshot(self, fingerprint):
        auth = self.auth_type.currentText()
        return {
            "host": self.host.text().strip(),
            "port": int(self.port.text() or 22),
            "username": self.username.text().strip(),
            "auth_type": auth,
            "password": self.password.text().strip() if auth == "password" else None,
            "private_key": (
                self.private_key.toPlainText().strip()
                if auth == "private_key" else None
            ),
            "private_key_passphrase": (
                self.passphrase.text().strip() or None
                if auth == "private_key" else None
            ),
            "trusted_host_fingerprint": fingerprint,
        }

    def _test_connection(self):
        host = self.host.text().strip()
        port = int(self.port.text() or 22)
        username = self.username.text().strip()
        auth = self.auth_type.currentText()
        stored_fp = self.fingerprint.text().strip()

        if not host or not username:
            QMessageBox.warning(self, "Missing Fields", "Host and Username are required.")
            return

        client = None
        try:
            fp_str = probe_ssh_host_fingerprint(host, port, timeout=8)
            if not stored_fp:
                resp = QMessageBox.question(
                    self,
                    "Unknown Host",
                    f"Server presented fingerprint:\n\n{fp_str}\n\nTrust this host?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if resp != QMessageBox.StandardButton.Yes:
                    return
                self.fingerprint.setText(fp_str)
            else:
                if normalize_fingerprint(stored_fp) != normalize_fingerprint(fp_str):
                    QMessageBox.warning(
                        self,
                        "Fingerprint Mismatch",
                        f"Stored fingerprint:\n{stored_fp}\n\n"
                        f"Server fingerprint:\n{fp_str}\n\n"
                        f"⚠️ POSSIBLE MITM ATTACK ⚠️"
                    )
                    return

            client, verified_fp = connect_ssh_profile(
                self._connection_snapshot(fp_str),
                timeout=8,
            )

            QMessageBox.information(
                self, "Connection OK",
                f"Connection successful.\n\nFingerprint:\n{verified_fp}"
            )

        except Exception as e:
            QMessageBox.critical(self, "Connection Failed", f"{e}")
        finally:
            try:
                if client:
                    client.close()
            except Exception:
                pass