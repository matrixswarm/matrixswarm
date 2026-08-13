# Authored by Daniel F MacDonald and ChatGPT-5.1 (“The Generals”)
from paramiko import RSAKey, Ed25519Key
import io, base64, uuid
from PyQt6.QtWidgets import QMessageBox
from hashlib import sha256
from PyQt6.QtWidgets import (
    QFormLayout, QLineEdit, QComboBox,
    QTextEdit, QPushButton
)
from .base_editor import BaseEditor
from matrix_gui.modules.railgun.ssh_support import (
    connect_ssh_profile,
    load_private_key,
    normalize_fingerprint,
    probe_ssh_host_fingerprint,
)

#from matrix_gui.core.class_lib.validation.network.private_key_utils import KeyValidator


class SSH(BaseEditor):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn)

        # Identity
        self.label = QLineEdit(self.generate_default_label())

        self.default_channel = QComboBox()
        default_channel_options = default_channel_options or ["ssh"]
        self.default_channel.addItems(default_channel_options)

        self.path_selector = QComboBox()
        # node directive path - add as you see fit
        self.path_selector.addItems([
            "config/ssh",  # default
            # "config/ssh_bk",
        ])

        self.key_type = QComboBox()
        self.key_type.addItems(["RSA", "Ed25519"])

        self.key_size = QComboBox()
        self.key_size.addItems(["2048", "3072", "4096"])  # only for RSA

        self.generate_btn = QPushButton("⚙️ Generate Key Pair")
        self.generate_btn.clicked.connect(self._generate_key_pair)


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
        # === Identity / Channel ===
        layout.addRow("Label", self.label)
        layout.addRow("Channel", self.default_channel)

        # === SSH Connection ===
        layout.addRow("Host", self.host)
        layout.addRow("Port", self.port)
        layout.addRow("Username", self.username)
        layout.addRow("Auth Type", self.auth_type)

        # === Authentication ===
        layout.addRow("Password", self.password)
        layout.addRow("Private Key", self.private_key)
        layout.addRow("Passphrase", self.passphrase)

        # === Security ===
        layout.addRow("Trusted Fingerprint", self.fingerprint)

        # === Key Generation Section ===
        self.key_type = QComboBox()
        self.key_type.addItems(["RSA", "Ed25519"])
        self.key_size = QComboBox()
        self.key_size.addItems(["2048", "3072", "4096"])  # RSA only

        # enable/disable key_size depending on type
        self.key_type.currentTextChanged.connect(
            lambda t: self.key_size.setEnabled(t == "RSA")
        )
        self.key_size.setEnabled(self.key_type.currentText() == "RSA")

        self.generate_btn = QPushButton("⚙️ Generate Key Pair")
        self.generate_btn.clicked.connect(self._generate_key_pair)
        self.public_key = QTextEdit()
        self.public_key.setReadOnly(True)
        self.public_key.setPlaceholderText("(Public key appears here after generation)")

        layout.addRow("Key Type", self.key_type)
        layout.addRow("Key Size", self.key_size)
        layout.addRow(self.generate_btn)
        layout.addRow("Public Key", self.public_key)

        layout.addRow("Directive Path", self.path_selector) #this is path in the json node where to put this
        layout.addRow("Serial", self.serial)
        self.test_btn = QPushButton("🔌 Test Connection")
        self.test_btn.clicked.connect(self._test_connection)
        layout.addRow(self.test_btn)

        # Visibility rules
        self.auth_type.currentTextChanged.connect(self._render_auth_mode)
        self._render_auth_mode(self.auth_type.currentText())

        self.private_key.setMinimumHeight(80)
        self.public_key.setMinimumHeight(50)
        self.private_key.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.public_key.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

    # --------------------------
    def _render_auth_mode(self, mode):
        """Show/hide fields depending on auth method."""
        self.password.setVisible(mode == "password")
        self.private_key.setVisible(mode == "private_key")
        self.passphrase.setVisible(mode == "private_key")

    def deploy_fields(self):
        out = {
            "host": self.host.text().strip(),
            "port": int(self.port.text() or 22),
            "username": self.username.text().strip(),
            "auth_type": self.auth_type.currentText(),
            "trusted_host_fingerprint": self.fingerprint.text().strip(),
        }

        mode = out["auth_type"]
        if mode == "password":
            out["password"] = self.password.text().strip()
            out["private_key"] = "None"
            out["private_key_passphrase"] = "None"

            # Generate a fresh random env variable name on each save
            env_name = f"PASSWORD_ENV_{uuid.uuid4().hex.upper()}"
            out["password_env"] = env_name
        elif mode == "private_key":
            out["private_key"] = self.private_key.toPlainText().strip()
            out["private_key_passphrase"] = self.passphrase.text().strip() or "None"
        elif mode == "agent":
            out["password"] = "None"
            out["private_key"] = "None"

        return out

    # --------------------------
    def on_load(self, data):

        path = data.get("node_directive_path", "config/ssh")
        self.path_selector.setCurrentText(path)

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

        self.default_channel.setCurrentText(data.get("channel", ""))

        self._render_auth_mode(mode)

    # --------------------------
    def serialize(self):
        self._ensure_serial()

        out = {
            "node_directive_path": self.path_selector.currentText().strip(),
            "serial": self.serial.text().strip(),
            "label": self.label.text().strip(),
            "channel": self.default_channel.currentText(),
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

        out['sensitive_fields']={"username": "1", "password": "1", "private_key": "1", "private_key_passphrase": "1"},

        return out

    def _generate_key_pair(self):
        """Generate a new private/public key pair and autofill fields."""


        key_type = self.key_type.currentText()
        key_size = int(self.key_size.currentText()) if key_type == "RSA" else None

        try:
            # --- Generate private key ---
            if key_type == "RSA":
                key = RSAKey.generate(bits=key_size)
            elif key_type == "Ed25519":
                key = Ed25519Key.generate()
            else:
                QMessageBox.warning(self, "Unsupported", f"Key type {key_type} not supported.")
                return

            # --- Export private key (PEM) ---
            private_io = io.StringIO()
            key.write_private_key(private_io)
            private_key_text = private_io.getvalue()

            # --- Export public key (authorized_keys format) ---
            public_key_text = f"{key.get_name()} {key.get_base64()} generated@phoenix"

            # --- Compute fingerprint ---
            raw = sha256(key.asbytes()).digest()
            fp = base64.b64encode(raw).decode()
            fp_str = f"SHA256:{fp}"

            # --- Autofill fields ---
            self.private_key.setPlainText(private_key_text)
            self.fingerprint.setText(fp_str)

            QMessageBox.information(
                self,
                "Key Generated",
                f"New {key_type} key pair created.\n\nFingerprint:\n{fp_str}\n\n"
                f"Public key:\n{public_key_text[:80]}..."
            )

            self.public_key.setPlainText(public_key_text)

        except Exception as e:
            QMessageBox.critical(self, "Key Generation Error", str(e))

    # --------------------------
    def is_validated(self):
        ok, msg = self._require_serial()
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