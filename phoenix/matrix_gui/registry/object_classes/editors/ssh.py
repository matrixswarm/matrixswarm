# Authored by Daniel F MacDonald and ChatGPT-5.1 (“The Generals”)
from paramiko import RSAKey, Ed25519Key
import io, base64, uuid
from pathlib import Path
import re
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox
from hashlib import sha256
from PyQt6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QComboBox,
    QTextEdit, QPushButton, QFileDialog,
    QGroupBox, QHBoxLayout, QTabWidget, QVBoxLayout, QWidget,
)
from .base_editor import BaseEditor
from matrix_gui.modules.railgun.ssh_support import (
    clean_secret,
    connect_ssh_profile,
    generate_strong_passphrase,
    load_private_key,
    normalize_fingerprint,
    probe_ssh_host_fingerprint,
    public_key_from_private_key,
    save_ssh_key_pair,
)

#from matrix_gui.core.class_lib.validation.network.private_key_utils import KeyValidator


class SSH(BaseEditor):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn)
        self._loaded_key_passphrase = None

        # Identity
        self.label = QLineEdit(self.generate_default_label())

        self.path_selector = QComboBox()
        # node directive path - add as you see fit
        self.path_selector.addItems([
            "config/ssh",  # default
            # "config/ssh_bk",
        ])

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
        self.apply_passphrase_btn = QPushButton("🔐 Apply Passphrase to Existing Key")
        self.apply_passphrase_btn.clicked.connect(self._apply_key_passphrase)
        self.generate_passphrase_btn = QPushButton("🎲 Generate Strong Passphrase")
        self.generate_passphrase_btn.clicked.connect(self._generate_passphrase)

        # Security
        self.fingerprint = QLineEdit()
        self.fingerprint.setPlaceholderText("SHA256:xxxxxx (host key fingerprint)")

        # Key management
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
        self.save_key_btn = QPushButton("💾 Save Key Pair to Disk")
        self.save_key_btn.clicked.connect(self._save_key_pair)
        self.install_key_btn = QPushButton("🚀 Install Public Key on Server")
        self.install_key_btn.clicked.connect(self._install_public_key)
        self.test_btn = QPushButton("🔌 Test Connection")
        self.test_btn.clicked.connect(self._test_connection)

        # Organized Registry layout: connection/trust stays separate from
        # credential and key-management operations.
        root_layout = QVBoxLayout(self)
        tabs = QTabWidget()
        root_layout.addWidget(tabs)

        connection_tab = QWidget()
        connection_layout = QVBoxLayout(connection_tab)

        profile_group = QGroupBox("Registry Identity")
        profile_form = QFormLayout(profile_group)
        profile_form.addRow("Label", self.label)
        profile_form.addRow("Directive Path", self.path_selector)
        profile_form.addRow("Serial", self.serial)
        connection_layout.addWidget(profile_group)

        server_group = QGroupBox("Server & Host Trust")
        server_form = QFormLayout(server_group)
        server_form.addRow("Host", self.host)
        server_form.addRow("Port", self.port)
        server_form.addRow("Username", self.username)
        server_form.addRow("Trusted Fingerprint", self.fingerprint)
        server_form.addRow(self.test_btn)
        connection_layout.addWidget(server_group)
        connection_layout.addStretch()
        tabs.addTab(connection_tab, "Connection")

        key_tab = QWidget()
        key_layout = QVBoxLayout(key_tab)

        auth_group = QGroupBox("Authentication")
        auth_form = QFormLayout(auth_group)
        self._auth_form = auth_form
        auth_form.addRow("Auth Type", self.auth_type)
        auth_form.addRow("Password / One-time Install", self.password)
        auth_form.addRow("Private Key", self.private_key)
        auth_form.addRow("Passphrase", self.passphrase)
        self.passphrase_actions = QWidget()
        passphrase_actions_layout = QHBoxLayout(self.passphrase_actions)
        passphrase_actions_layout.setContentsMargins(0, 0, 0, 0)
        passphrase_actions_layout.addWidget(self.apply_passphrase_btn)
        passphrase_actions_layout.addWidget(self.generate_passphrase_btn)
        auth_form.addRow(self.passphrase_actions)
        key_layout.addWidget(auth_group)

        generation_group = QGroupBox("Key Pair")
        generation_form = QFormLayout(generation_group)
        key_options = QWidget()
        key_options_layout = QHBoxLayout(key_options)
        key_options_layout.setContentsMargins(0, 0, 0, 0)
        key_options_layout.addWidget(self.key_type)
        key_options_layout.addWidget(self.key_size)
        generation_form.addRow("Type / Size", key_options)
        generation_form.addRow(self.generate_btn)
        generation_form.addRow("Public Key", self.public_key)

        key_actions = QWidget()
        key_actions_layout = QHBoxLayout(key_actions)
        key_actions_layout.setContentsMargins(0, 0, 0, 0)
        key_actions_layout.addWidget(self.save_key_btn)
        key_actions_layout.addWidget(self.install_key_btn)
        generation_form.addRow(key_actions)
        key_layout.addWidget(generation_group)
        key_layout.addStretch()
        tabs.addTab(key_tab, "Authentication & Keys")

        # Visibility rules
        self.auth_type.currentTextChanged.connect(self._render_auth_mode)
        self._render_auth_mode(self.auth_type.currentText())

        self.private_key.setMinimumHeight(100)
        self.public_key.setMinimumHeight(70)
        self.private_key.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.public_key.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

    # --------------------------
    def _render_auth_mode(self, mode):
        """Show/hide fields depending on auth method."""
        credential_mode = mode in ("password", "private_key")
        for widget in (self.password, self.private_key, self.passphrase):
            widget.setVisible(credential_mode)
            label = self._auth_form.labelForField(widget)
            if label is not None:
                label.setVisible(credential_mode)
        self.apply_passphrase_btn.setVisible(mode == "private_key")
        self.passphrase_actions.setVisible(credential_mode)

    def deploy_fields(self):
        out = {
            "proto": "ssh",
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

        out["sensitive_fields"] = {
            "username": "1",
            "password": "1",
            "private_key": "1",
            "private_key_passphrase": "1",
        }
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

        self.password.setText(clean_secret(data.get("password")) or "")
        self.private_key.setText(clean_secret(data.get("private_key")) or "")
        loaded_passphrase = clean_secret(data.get("private_key_passphrase"))
        self._loaded_key_passphrase = loaded_passphrase
        self.passphrase.setText(loaded_passphrase or "")

        self.fingerprint.setText(str(data.get("trusted_host_fingerprint", "")))

        self._render_auth_mode(mode)
        self._refresh_public_key()

    # --------------------------
    def serialize(self):
        self._ensure_serial()

        out = {
            "node_directive_path": self.path_selector.currentText().strip(),
            "serial": self.serial.text().strip(),
            "label": self.label.text().strip(),
            "host": self.host.text().strip(),
            "port": int(self.port.text() or 22),
            "username": self.username.text().strip(),
            "auth_type": self.auth_type.currentText(),
            "trusted_host_fingerprint": self.fingerprint.text().strip(),
        }

        if out["auth_type"] == "password":
            out["password"] = self.password.text().strip()
            # Preserve an optional generated key in the encrypted Registry so
            # the installer can authenticate with the password and then verify
            # the new key independently, without discarding the password.
            out["private_key"] = (
                self.private_key.toPlainText().strip() or "None"
            )
            out["private_key_passphrase"] = (
                self.passphrase.text().strip() or "None"
            )

        elif out["auth_type"] == "private_key":
            out["private_key"] = self.private_key.toPlainText().strip()
            out["private_key_passphrase"] = self.passphrase.text().strip() or "None"
            out["password"] = self.password.text().strip() or "None"

        out["sensitive_fields"] = {
            "username": "1",
            "password": "1",
            "private_key": "1",
            "private_key_passphrase": "1",
        }

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
            passphrase = clean_secret(self.passphrase.text())
            key.write_private_key(private_io, password=passphrase)
            private_key_text = private_io.getvalue()
            self._loaded_key_passphrase = passphrase

            # --- Export public key (authorized_keys format) ---
            public_key_text = f"{key.get_name()} {key.get_base64()} generated@phoenix"

            # --- Compute fingerprint ---
            raw = sha256(key.asbytes()).digest()
            fp = base64.b64encode(raw).decode()
            fp_str = f"SHA256:{fp}"

            # --- Autofill fields ---
            self.private_key.setPlainText(private_key_text)
            QMessageBox.information(
                self,
                "Key Generated",
                f"New {key_type} key pair created "
                f"({'with passphrase protection' if passphrase else 'without a passphrase'})."
                f"\n\nClient-key fingerprint:\n{fp_str}\n\n"
                f"Public key:\n{public_key_text[:80]}..."
            )

            self.public_key.setPlainText(public_key_text)

        except Exception as e:
            QMessageBox.critical(self, "Key Generation Error", str(e))

    def _key_material(self):
        private_key = self.private_key.toPlainText().strip()
        passphrase = clean_secret(self.passphrase.text())
        public_key = public_key_from_private_key(
            private_key,
            passphrase,
            comment=f"phoenix@{self.host.text().strip() or 'ssh'}",
        )
        return private_key, passphrase, public_key

    def _refresh_public_key(self):
        try:
            _private, _passphrase, public_key = self._key_material()
        except (ValueError, TypeError):
            self.public_key.clear()
            return
        self.public_key.setPlainText(public_key)

    def _default_key_path(self):
        label = self.label.text().strip() or self.host.text().strip() or "phoenix_ssh"
        filename = re.sub(r"[^A-Za-z0-9._-]+", "_", label).strip("._")
        return str(Path.home() / ".ssh" / (filename or "phoenix_ssh"))

    def _save_key_pair(self):
        try:
            private_key, _passphrase, public_key = self._key_material()
        except Exception as exc:
            QMessageBox.warning(self, "Cannot Save Key", str(exc))
            return

        filename, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save SSH Private Key",
            self._default_key_path(),
            "SSH Private Keys (*);;All Files (*)",
        )
        if not filename:
            return
        key_paths = [Path(filename), Path(filename + ".pub")]
        existing = [str(path) for path in key_paths if path.exists()]
        if existing and QMessageBox.question(
            self,
            "Replace Existing Key Files",
            "Replace these existing key files?\n\n" + "\n".join(existing),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        try:
            private_path, public_path = save_ssh_key_pair(
                filename, private_key, public_key
            )
        except Exception as exc:
            QMessageBox.critical(self, "Key Save Failed", str(exc))
            return
        QMessageBox.information(
            self,
            "Key Pair Saved",
            f"Private key:\n{private_path}\n\nPublic key:\n{public_path}\n\n"
            "The private key was written with restricted permissions.",
        )

    def _verified_host_fingerprint(self):
        host = self.host.text().strip()
        port = int(self.port.text() or 22)
        actual = probe_ssh_host_fingerprint(host, port, timeout=8)
        stored = self.fingerprint.text().strip()
        if not stored:
            response = QMessageBox.question(
                self,
                "Unknown Host",
                f"Server presented fingerprint:\n\n{actual}\n\nTrust this host?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if response != QMessageBox.StandardButton.Yes:
                return None
            self.fingerprint.setText(actual)
        elif normalize_fingerprint(stored) != normalize_fingerprint(actual):
            raise ValueError(
                "SSH host-key fingerprint mismatch. The key was not installed."
            )
        return actual

    def _install_public_key(self):
        """Install the editor's key using a separately selected vaulted login."""
        from matrix_gui.registry.ssh_key_install_dialog import (
            VaultSSHKeyInstallDialog,
        )

        try:
            key_profile = self.serialize()
            self._key_material()  # Validate the exact editor key before opening.
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Cannot Install Key", str(exc))
            return
        dialog = VaultSSHKeyInstallDialog(
            self,
            selected_serial=self.serial.text().strip(),
            key_profile=key_profile,
        )
        dialog.exec()
        if dialog.installed_key_profile is not None:
            self.on_load(dialog.installed_key_profile)
        elif dialog.updated_profile:
            if dialog.updated_serial == self.serial.text().strip():
                self.on_load(dialog.updated_profile)

    def _generate_passphrase(self):
        """Review and adopt a cryptographically random 48-character passphrase."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Generate Strong SSH Passphrase")
        dialog.setMinimumWidth(680)
        layout = QVBoxLayout(dialog)

        explanation = QLabel(
            "Phoenix generated this passphrase with the operating system's "
            "cryptographic random source. Store it securely before using it; "
            "losing it makes the encrypted private key unusable."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        generated = QLineEdit(generate_strong_passphrase())
        generated.setReadOnly(True)
        generated.setEchoMode(QLineEdit.EchoMode.Normal)
        layout.addWidget(generated)

        status = QLabel(
            "Copy is optional. If used, Phoenix clears the clipboard after "
            "60 seconds when it still contains this passphrase."
        )
        status.setWordWrap(True)
        layout.addWidget(status)

        action_row = QHBoxLayout()
        regenerate_btn = QPushButton("Regenerate")
        copy_btn = QPushButton("Copy for 60 Seconds")
        action_row.addWidget(regenerate_btn)
        action_row.addWidget(copy_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Use Passphrase"
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def regenerate():
            generated.setText(generate_strong_passphrase())
            generated.selectAll()

        def copy_temporarily():
            copied = generated.text()
            clipboard = QApplication.clipboard()
            clipboard.setText(copied)
            status.setText(
                "Copied. Phoenix will clear the clipboard in 60 seconds if "
                "the clipboard still contains this passphrase."
            )

            def clear_if_unchanged():
                if clipboard.text() == copied:
                    clipboard.clear()

            QTimer.singleShot(60_000, clear_if_unchanged)

        regenerate_btn.clicked.connect(regenerate)
        copy_btn.clicked.connect(copy_temporarily)
        generated.selectAll()
        generated.setFocus()

        if dialog.exec():
            self.passphrase.setText(generated.text())
            self.passphrase.setEchoMode(QLineEdit.EchoMode.Password)

    def _apply_key_passphrase(self):
        """Encrypt the current private key without changing its key pair."""
        key_text = self.private_key.toPlainText().strip()
        new_passphrase = clean_secret(self.passphrase.text())
        if not key_text:
            QMessageBox.warning(self, "Missing Key", "Private Key is required.")
            return
        if not new_passphrase:
            QMessageBox.warning(
                self,
                "Missing Passphrase",
                "Enter a new passphrase before applying it to the private key.",
            )
            return

        try:
            try:
                key = load_private_key(key_text, self._loaded_key_passphrase)
            except ValueError:
                # Profiles created by the old editor may contain an arbitrary
                # passphrase beside a key that was never encrypted.
                key = load_private_key(key_text, None)

            protected = io.StringIO()
            key.write_private_key(protected, password=new_passphrase)
            protected_text = protected.getvalue()
            load_private_key(protected_text, new_passphrase)

            self.private_key.setPlainText(protected_text)
            self._loaded_key_passphrase = new_passphrase
            self.public_key.setPlainText(
                f"{key.get_name()} {key.get_base64()} protected@phoenix"
            )
            QMessageBox.information(
                self,
                "Passphrase Applied",
                "The existing private key is now encrypted. Its public key "
                "and the server's authorized_keys entry did not change.",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Passphrase Error", str(exc))

    # --------------------------
    def is_validated(self):
        ok, msg = self._require_serial()
        if not ok:
            return ok, msg

        if not self.label.text().strip():
            return False, "Label is required."

        if not self.host.text().strip():
            return False, "Host is required."

        if not self.username.text().strip():
            return False, "Username is required."

        if not self.port.text().isdigit():
            return False, "Port must be numeric."
        try:
            port = int(self.port.text())
        except ValueError:
            return False, "Port must be numeric."
        if not 1 <= port <= 65535:
            return False, "Port must be between 1 and 65535."

        method = self.auth_type.currentText()
        if method == "password" and not self.password.text().strip():
            return False, "Password required for password auth."

        if method == "private_key" and not self.private_key.toPlainText().strip():
            return False, "Private key required."

        if self.private_key.toPlainText().strip():
            try:
                load_private_key(
                    self.private_key.toPlainText(),
                    self.passphrase.text(),
                )
            except ValueError as exc:
                return False, str(exc)

        if not self.fingerprint.text().strip():
            return False, "Trusted SHA256 host fingerprint is required."
        fingerprint = self.fingerprint.text().strip()
        # Accept OpenSSH's unpadded SHA256 form and the padded form Phoenix
        # generates, but require a canonical 32-byte digest (not just a prefix).
        if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}=?", fingerprint):
            return False, "Trusted fingerprint must be a SHA256 SSH host fingerprint."
        encoded = fingerprint[7:].rstrip("=")
        digest = base64.b64decode(encoded + "=", validate=True)
        if len(digest) != 32 or base64.b64encode(digest).decode().rstrip("=") != encoded:
            return False, "Trusted fingerprint must encode a valid SHA256 digest."

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
        username = self.username.text().strip()

        if not host or not username:
            QMessageBox.warning(self, "Missing Fields", "Host and Username are required.")
            return

        client = None
        try:
            fp_str = self._verified_host_fingerprint()
            if not fp_str:
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
