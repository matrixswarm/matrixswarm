"""Vault-backed, idempotent SSH public-key onboarding dialog."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from matrix_gui.modules.railgun.ssh_support import (
    clean_secret,
    connect_ssh_profile,
    format_ssh_profile_label,
    install_authorized_key,
    load_private_key,
    load_registry_ssh_profiles,
    normalize_fingerprint,
    probe_ssh_host_fingerprint,
    public_key_from_private_key,
    save_ssh_key_pair,
    sha256_fingerprint,
    validate_ssh_install_target,
)
from matrix_gui.modules.vault.services.vault_core_singleton import (
    VaultCoreSingleton,
)


class VaultSSHKeyInstallDialog(QDialog):
    """Use vaulted login credentials to install an independently selected key."""

    def __init__(self, parent=None, selected_serial=None, key_profile=None):
        super().__init__(parent)
        self.selected_serial = str(selected_serial or "")
        self.updated_serial = None
        self.updated_profile = None
        self.key_profile = deepcopy(key_profile) if key_profile is not None else None
        self.installed_key_profile = None
        self.registry_store = VaultCoreSingleton.get().get_store("registry")

        self.setWindowTitle("Install SSH Public Key")
        self.setMinimumWidth(720)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Install the current editor's key using an existing Vault login. "
            "Host, port, account and pinned host key must match. Verification uses "
            "only the new private key. Save the editor with OK afterward; the "
            "selected login profile is not changed."
            if self.key_profile is not None else
            "Select a vaulted SSH profile to install its saved public key. "
            "Installation never removes the SSH login password."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        target_group = QGroupBox("Existing Vault Login")
        target_form = QFormLayout(target_group)
        self.profile_combo = QComboBox()
        self.target_value = QLabel("—")
        self.auth_value = QLabel("—")
        self.fingerprint_value = QLabel("—")
        self.vault_password_value = QLabel("—")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText(
            "Optional override; leave blank to use Login Method"
        )
        self.password_input.setToolTip(
            "Leave blank to use the selected profile's authentication method. "
            "Enter a password to use it for this installation only; it is not saved."
        )
        target_form.addRow("Profile", self.profile_combo)
        target_form.addRow("Target", self.target_value)
        target_form.addRow("Login Method", self.auth_value)
        target_form.addRow("Pinned Host Key", self.fingerprint_value)
        target_form.addRow("Vault Password", self.vault_password_value)
        target_form.addRow("One-Time Password", self.password_input)
        root.addWidget(target_group)

        key_group = QGroupBox("Key to Install")
        key_form = QFormLayout(key_group)
        self.key_source_value = QLabel()
        self.key_target_value = QLabel()
        self.key_fingerprint_value = QLabel()
        self.target_pin_value = QLabel()
        self.match_value = QLabel()
        self.match_value.setWordWrap(True)
        self.remote_path_value = QLineEdit("Pending login: ~/.ssh/authorized_keys")
        self.remote_path_value.setReadOnly(True)
        key_form.addRow("Key Source", self.key_source_value)
        key_form.addRow("Install Target", self.key_target_value)
        key_form.addRow("Client-Key Fingerprint", self.key_fingerprint_value)
        key_form.addRow("Target Host Pin", self.target_pin_value)
        key_form.addRow("Remote File", self.remote_path_value)
        key_form.addRow(self.match_value)
        root.addWidget(key_group)

        export_group = QGroupBox("Restricted Local Key Export")
        export_form = QFormLayout(export_group)
        path_row = QHBoxLayout()
        self.path_input = QLineEdit()
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._browse)
        path_row.addWidget(self.path_input, 1)
        path_row.addWidget(self.browse_btn)
        export_form.addRow("Private Key File", path_row)
        export_note = QLabel(
            "Phoenix writes the private key with restricted permissions and "
            "writes the public key beside it with a .pub suffix."
        )
        export_note.setWordWrap(True)
        export_form.addRow(export_note)
        root.addWidget(export_group)

        actions = QHBoxLayout()
        actions.addStretch()
        self.save_btn = QPushButton("Save Private + Public Keys")
        self.install_btn = QPushButton("Install && Verify Public Key")
        self.remove_password_btn = QPushButton(
            "Verify && Remove Vault Password"
        )
        self.cancel_btn = QPushButton("Cancel")
        self.save_btn.clicked.connect(self._save_only)
        self.install_btn.clicked.connect(self._install)
        self.remove_password_btn.clicked.connect(self._remove_password)
        # This legacy action affects the selected Vault login, not an editor key.
        self.remove_password_btn.setVisible(self.key_profile is None)
        self.cancel_btn.clicked.connect(self.reject)
        actions.addWidget(self.save_btn)
        actions.addWidget(self.install_btn)
        actions.addWidget(self.remove_password_btn)
        actions.addWidget(self.cancel_btn)
        root.addLayout(actions)

        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self._load_profiles()

    def _load_profiles(self):
        profiles = load_registry_ssh_profiles()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("Select vaulted SSH profile…", None)
        selected_index = -1
        for serial, profile in sorted(
            profiles.items(),
            key=lambda item: format_ssh_profile_label(*item).casefold(),
        ):
            self.profile_combo.addItem(
                format_ssh_profile_label(serial, profile), serial
            )
            if serial == self.selected_serial:
                selected_index = self.profile_combo.count() - 1
        self.profile_combo.blockSignals(False)
        if self.profile_combo.count() == 1:
            self._set_actions_enabled(False)
            self.target_value.setText("No SSH profiles are stored in the Vault.")
            self._refresh_key_preview(None)
            return
        self.profile_combo.setCurrentIndex(max(0, selected_index))
        self._profile_changed()

    def _current(self):
        serial = self.profile_combo.currentData()
        if not serial:
            return None, None
        profile = load_registry_ssh_profiles().get(str(serial))
        return str(serial), profile

    def _key_source(self, login_profile):
        return self.key_profile if self.key_profile is not None else login_profile

    def _refresh_key_preview(self, login_profile):
        source = self._key_source(login_profile)
        self.key_source_value.setText(
            "Current editor (including unsaved changes)"
            if self.key_profile is not None else "Selected saved Vault profile"
        )
        self.remote_path_value.setText("Pending login: ~/.ssh/authorized_keys")
        if not source:
            for label in (self.key_target_value, self.key_fingerprint_value, self.target_pin_value):
                label.setText("—")
            self.match_value.setText("Select a Vault login profile.")
            return
        self.key_target_value.setText(
            f"{source.get('username', '?')}@{source.get('host', '?')}:{source.get('port', 22)}"
        )
        self.target_pin_value.setText(
            clean_secret(source.get("trusted_host_fingerprint")) or "Not pinned"
        )
        self.path_input.setText(self._default_key_path(source))
        try:
            key = load_private_key(source.get("private_key"), source.get("private_key_passphrase"))
            self.key_fingerprint_value.setText(sha256_fingerprint(key))
            self.save_btn.setEnabled(True)
        except (ValueError, TypeError):
            self.key_fingerprint_value.setText("Invalid key or passphrase")
            self.save_btn.setEnabled(False)
            self.install_btn.setEnabled(False)
            self.match_value.setText("Correct the key and passphrase before installing.")
            return
        try:
            if not login_profile:
                raise ValueError("Select a Vault login profile.")
            if self.key_profile is not None:
                validate_ssh_install_target(source, login_profile)
        except ValueError as exc:
            self.match_value.setText(str(exc))
            self.install_btn.setEnabled(False)
        else:
            self.match_value.setText("Target matches. The live server host key will also be verified.")
            self.install_btn.setEnabled(True)

    @staticmethod
    def _default_key_path(profile):
        label = (
            clean_secret(profile.get("label"))
            or clean_secret(profile.get("host"))
            or "phoenix_ssh"
        )
        filename = re.sub(r"[^A-Za-z0-9._-]+", "_", label).strip("._")
        return str(Path.home() / ".ssh" / (filename or "phoenix_ssh"))

    def _profile_changed(self):
        _serial, profile = self._current()
        if not profile:
            self._set_actions_enabled(False)
            self.target_value.setText("—")
            self.auth_value.setText("—")
            self.fingerprint_value.setText("—")
            self.vault_password_value.setText("—")
            self.password_input.clear()
            self.path_input.clear()
            self._refresh_key_preview(None)
            return
        host = clean_secret(profile.get("host")) or "?"
        user = clean_secret(profile.get("username")) or "?"
        port = profile.get("port", 22)
        auth = clean_secret(profile.get("auth_type")) or "?"
        fingerprint = clean_secret(profile.get("trusted_host_fingerprint"))
        has_password = bool(clean_secret(profile.get("password")))
        self.target_value.setText(f"{user}@{host}:{port}")
        self.auth_value.setText(auth)
        self.fingerprint_value.setText(fingerprint or "Not pinned")
        self.vault_password_value.setText(
            "Stored" if has_password else "Not stored"
        )
        self.password_input.clear()
        self.path_input.setText(self._default_key_path(profile))
        self.save_btn.setEnabled(True)
        self.install_btn.setEnabled(True)
        self.remove_password_btn.setEnabled(has_password)
        self._refresh_key_preview(profile)

    def _set_actions_enabled(self, enabled):
        self.save_btn.setEnabled(enabled)
        self.install_btn.setEnabled(enabled)
        self.remove_password_btn.setEnabled(enabled)

    def _browse(self):
        filename, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save SSH Private Key",
            self.path_input.text().strip(),
            "SSH Private Keys (*);;All Files (*)",
        )
        if filename:
            self.path_input.setText(filename)

    def _confirm_export_replace(self, filename):
        existing = [
            path for path in (Path(filename), Path(filename + ".pub"))
            if path.exists()
        ]
        if not existing:
            return True
        paths = "\n".join(str(path) for path in existing)
        return QMessageBox.question(
            self,
            "Replace Existing Key Files",
            f"Replace these existing key files?\n\n{paths}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    def _verified_fingerprint(self, profile):
        host = clean_secret(profile.get("host"))
        port = int(profile.get("port", 22))
        actual = probe_ssh_host_fingerprint(host, port, timeout=8)
        stored = clean_secret(profile.get("trusted_host_fingerprint"))
        if stored:
            if normalize_fingerprint(stored) != normalize_fingerprint(actual):
                raise ValueError(
                    "SSH host-key fingerprint mismatch. Nothing was installed."
                )
            return actual
        response = QMessageBox.question(
            self,
            "Unknown SSH Host",
            f"Server presented fingerprint:\n\n{actual}\n\nTrust this host?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return actual if response == QMessageBox.StandardButton.Yes else None

    @staticmethod
    def _key_material(profile):
        private_key = clean_secret(profile.get("private_key"))
        passphrase = clean_secret(profile.get("private_key_passphrase"))
        if not private_key:
            raise ValueError(
                "The key source has no private key. Generate or load "
                "one in the SSH Registry editor first."
            )
        public_key = public_key_from_private_key(
            private_key,
            passphrase,
            comment=f"phoenix@{profile.get('host', 'ssh')}",
        )
        return private_key, passphrase, public_key

    def _installation_auth_profile(self, profile, fingerprint):
        candidate = dict(profile)
        password = clean_secret(self.password_input.text())
        if password:
            candidate.update(auth_type="password", password=password)
        else:
            # Match Test Connection: merely retaining a password in the Vault
            # must not override the operator's selected authentication method.
            auth_type = str(profile.get("auth_type", "private_key")).strip().lower()
            if auth_type not in ("password", "private_key", "agent"):
                raise ValueError("Select a supported SSH authentication method.")
            if auth_type == "password" and not clean_secret(profile.get("password")):
                raise ValueError(
                    "Password authentication is selected, but no vaulted password "
                    "is available. Enter a one-time password or update the profile."
                )
            candidate["auth_type"] = auth_type
            if auth_type != "password":
                candidate.pop("password", None)
        candidate["trusted_host_fingerprint"] = fingerprint
        return candidate

    @staticmethod
    def _private_key_profile(profile, fingerprint):
        candidate = dict(profile)
        candidate.pop("password", None)
        candidate.update(
            auth_type="private_key",
            trusted_host_fingerprint=fingerprint,
        )
        return candidate

    def _commit_profile(self, serial, updated):
        namespace = self.registry_store.get_namespace("ssh")
        original = deepcopy(namespace.get(serial))
        if original is None:
            raise RuntimeError("The selected SSH profile no longer exists")

        # Remove old runtime-policy leakage whenever this dialog writes the
        # shared credential record.
        for stale_field in ("channel", "default_channel", "ssh_mode"):
            updated.pop(stale_field, None)
        updated.setdefault("meta", {})["modified"] = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        namespace[serial] = updated
        if not self.registry_store.commit():
            namespace[serial] = original
            raise RuntimeError("Vault rejected the SSH profile update")

        self.updated_serial = serial
        self.updated_profile = deepcopy(updated)
        self.auth_value.setText(clean_secret(updated.get("auth_type")) or "?")
        self.fingerprint_value.setText(
            clean_secret(updated.get("trusted_host_fingerprint")) or "Not pinned"
        )
        has_password = bool(clean_secret(updated.get("password")))
        self.vault_password_value.setText(
            "Stored" if has_password else "Not stored"
        )
        self.remove_password_btn.setEnabled(has_password)

    def _save_only(self):
        _serial, profile = self._current()
        profile = self._key_source(profile)
        if not profile:
            QMessageBox.warning(self, "Missing Profile", "Select an SSH profile.")
            return
        filename = self.path_input.text().strip()
        if not filename:
            QMessageBox.warning(
                self, "Missing Export Path", "Choose a private-key file path."
            )
            return
        if not self._confirm_export_replace(filename):
            return

        try:
            private_key, _passphrase, public_key = self._key_material(profile)
            private_path, public_path = save_ssh_key_pair(
                filename, private_key, public_key
            )
            QMessageBox.information(
                self,
                "SSH Key Pair Saved",
                f"Private key:\n{private_path}\n\nPublic key:\n{public_path}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "SSH Key Export Failed", str(exc))

    def _install(self):
        serial, profile = self._current()
        if not profile:
            QMessageBox.warning(self, "Missing Profile", "Select an SSH profile.")
            return

        filename = self.path_input.text().strip()
        if not filename:
            QMessageBox.warning(
                self, "Missing Export Path", "Choose a private-key file path."
            )
            return
        if not self._confirm_export_replace(filename):
            return

        install_client = None
        key_client = None
        stage = "Checking installation target"
        try:
            source = deepcopy(self._key_source(profile))
            if self.key_profile is not None:
                validate_ssh_install_target(source, profile)
            stage = "Preparing the key pair"
            private_key, passphrase, public_key = self._key_material(source)
            client_fingerprint = sha256_fingerprint(load_private_key(private_key, passphrase))
            stage = "Verifying the SSH host fingerprint"
            fingerprint = self._verified_fingerprint(profile)
            if not fingerprint:
                return

            stage = "Selecting installation authentication"
            install_profile = self._installation_auth_profile(profile, fingerprint)
            stage = f"Authenticating for installation using {install_profile['auth_type']}"
            install_client, _actual = connect_ssh_profile(
                install_profile, timeout=8
            )
            stage = "Installing the public key"
            result = install_authorized_key(install_client, public_key)
            self.remote_path_value.setText(result.remote_path)
            self.remote_path_value.setToolTip(result.remote_path)
            install_client.close()
            install_client = None

            stage = "Verifying private-key login"
            key_client, _actual = connect_ssh_profile(
                self._private_key_profile(source, fingerprint), timeout=8
            )
            key_client.close()
            key_client = None

            stage = "Saving the local key pair"
            private_path, public_path = save_ssh_key_pair(
                filename, private_key, public_key
            )

            updated = deepcopy(source)
            updated["auth_type"] = "private_key"
            updated["private_key"] = private_key
            updated["private_key_passphrase"] = passphrase or "None"
            updated["trusted_host_fingerprint"] = fingerprint
            if self.key_profile is None:
                stage = "Saving the Vault profile"
                self._commit_profile(serial, updated)
                save_note = "The Vault profile was updated; its SSH login password was retained."
            else:
                self.installed_key_profile = updated
                save_note = (
                    "The selected Vault login profile was not changed. "
                    "Close this dialog and click OK in the editor to save the new credentials."
                )
            self.password_input.clear()
            key_action = "installed" if result.installed else "already present"
            QMessageBox.information(
                self,
                "SSH Key Onboarding Complete",
                f"The public key was {key_action}; no duplicate was added.\n\n"
                f"Client-key fingerprint:\n{client_fingerprint}\n\n"
                f"Target: {source['username']}@{source['host']}:{source.get('port', 22)}\n"
                f"Verified host key:\n{fingerprint}\n\nRemote file:\n{result.remote_path}\n\n"
                "A fresh login using only this private key succeeded.\n\n"
                f"{save_note}\n\nPrivate key:\n{private_path}\n\nPublic key:\n"
                f"{public_path}",
            )
        except Exception as exc:
            QMessageBox.critical(
                self, "SSH Key Installation Failed", f"{stage} failed.\n\n{exc}"
            )
        finally:
            for client in (install_client, key_client):
                try:
                    if client:
                        client.close()
                except Exception:
                    pass

    def _remove_password(self):
        serial, profile = self._current()
        if not profile:
            QMessageBox.warning(self, "Missing Profile", "Select an SSH profile.")
            return
        if not clean_secret(profile.get("password")):
            QMessageBox.information(
                self,
                "No Vault Password",
                "This SSH profile does not contain a vaulted password.",
            )
            return
        try:
            self._key_material(profile)
        except Exception as exc:
            QMessageBox.warning(self, "Private Key Required", str(exc))
            return

        confirmed = QMessageBox.question(
            self,
            "Remove Vault Password",
            "Phoenix will first perform a fresh private-key login. Remove the "
            "vaulted SSH password only if that verification succeeds?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return

        key_client = None
        try:
            fingerprint = self._verified_fingerprint(profile)
            if not fingerprint:
                return
            key_client, _actual = connect_ssh_profile(
                self._private_key_profile(profile, fingerprint), timeout=8
            )
            key_client.close()
            key_client = None

            updated = deepcopy(profile)
            updated["auth_type"] = "private_key"
            updated["trusted_host_fingerprint"] = fingerprint
            updated["password"] = "None"
            updated.pop("password_env", None)
            self._commit_profile(serial, updated)
            QMessageBox.information(
                self,
                "Vault Password Removed",
                "Private-key login succeeded. The SSH password was then "
                "removed from this Vault profile.",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Password Removal Blocked",
                "The vaulted password was retained.\n\n" + str(exc),
            )
        finally:
            try:
                if key_client:
                    key_client.close()
            except Exception:
                pass
