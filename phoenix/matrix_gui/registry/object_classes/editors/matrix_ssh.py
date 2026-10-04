"""Matrix SSH route composed with a reusable SSH registry credential."""
from copy import deepcopy

from PyQt6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLineEdit, QGroupBox, QLabel
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.registry.terminal_fields import fields_visible, ssh_target
from .base_editor import BaseEditor
from .ssh import SSH


class MatrixSSH(BaseEditor):
    def __init__(self, parent=None, new_conn=False, default_channel_options=None, *, terminal_mode=False):
        super().__init__(parent, default_channel_options)
        self._metadata = {}
        self._show_terminal_fields = fields_visible(terminal_mode=terminal_mode)
        self.label = QLineEdit(self.generate_default_label())
        self.ssh = QComboBox()
        self.target_server = QComboBox()
        self.target_server.addItem("Select target server…", None)
        targets = []
        for record in self._ssh_records().values():
            try:
                target = ssh_target(record) if isinstance(record, dict) else None
            except ValueError:
                continue
            if target and target not in targets:
                targets.append(target)
                self.target_server.addItem(self._target_label(target), target)
        self.terminal_group = QGroupBox("Terminal Mode — SSH target")
        terminal_layout = QFormLayout(self.terminal_group)
        terminal_layout.addRow("Target server:", self.target_server)
        help_label = QLabel(
            "Narrows SSH choices by host, port and pinned host key. "
            "The selected profile is fixed in the saved terminal metadata. "
            "No terminal permission or connection is granted."
        )
        help_label.setWordWrap(True)
        terminal_layout.addRow(help_label)
        self.terminal_group.setVisible(self._show_terminal_fields)
        self.target_server.currentIndexChanged.connect(self._populate_ssh)
        self._populate_ssh()
        self.default_channel = QComboBox()
        self.default_channel.addItem("outgoing.command")
        self.default_outgoing = QCheckBox("Primary Outgoing Transport")
        self.path_selector = QComboBox()
        self.path_selector.addItem("config")
        layout = QFormLayout(self)
        layout.addRow("Label", self.label)
        layout.addRow(self.terminal_group)
        layout.addRow("SSH Profile", self.ssh)
        layout.addRow("Channel", self.default_channel)
        layout.addRow("", self.default_outgoing)
        layout.addRow("Serial", self.serial)

    @staticmethod
    def _ssh_records():
        return VaultCoreSingleton.get().get_store("registry").get_namespace("ssh")

    def on_load(self, data):
        self._metadata = deepcopy(data.get("meta", {}))
        if not isinstance(self._metadata, dict):
            raise ValueError("Registry metadata must be an object.")
        terminal = self._metadata.get("terminal", {})
        target = terminal.get("target_server") if isinstance(terminal, dict) else None
        self.target_server.blockSignals(True)
        try:
            index = self.target_server.findData(target) if isinstance(target, dict) else 0
            if index < 0:
                self.target_server.addItem("Saved target (not currently available)", deepcopy(target))
                index = self.target_server.count() - 1
            self.target_server.setCurrentIndex(index)
        finally:
            self.target_server.blockSignals(False)
        self._populate_ssh()
        self.label.setText(str(data.get("label", "")))
        self.serial.setText(str(data.get("serial", "")))
        selected = str(data.get("ssh_serial", ""))
        index = self.ssh.findData(selected)
        if index < 0 and selected:
            self.ssh.addItem(f"Missing or nonmatching SSH profile · {selected}", selected)
            index = self.ssh.count() - 1
        self.ssh.setCurrentIndex(max(0, index))
        channel = data.get("channel", "outgoing.command")
        if self.default_channel.findText(str(channel)) < 0:
            self.default_channel.addItem(str(channel))
        self.default_channel.setCurrentText(str(channel))
        self.default_outgoing.setChecked(data.get("default_outgoing") is True)

    def serialize(self):
        self._ensure_serial()
        result = {
            "label": self.label.text().strip(),
            "serial": self.serial.text().strip(),
            "ssh_serial": self.ssh.currentData(),
            "channel": self.default_channel.currentText(),
            "default_outgoing": self.default_outgoing.isChecked(),
            "node_directive_path": "config",
        }
        metadata = deepcopy(self._metadata)
        if self._show_terminal_fields:
            ok, message = self._validate_terminal_fields()
            if not ok:
                raise ValueError(message)
            terminal = deepcopy(metadata.get("terminal", {}))
            terminal.update(schema_version=1, target_server=deepcopy(self.target_server.currentData()),
                            ssh_serial=self.ssh.currentData(),
                            username=str(self._ssh_records()[self.ssh.currentData()].get("username", "")).strip())
            metadata["terminal"] = terminal
        if metadata:
            result["meta"] = metadata
        return result

    @staticmethod
    def _target_label(target):
        return f"{target['host']}:{target['port']} · {target['trusted_host_fingerprint']}"

    def _populate_ssh(self, _index=None):
        selected = self.ssh.currentData()
        self.ssh.clear()
        self.ssh.addItem("Select SSH…", None)
        target = self.target_server.currentData()
        for serial, record in self._ssh_records().items():
            if not isinstance(record, dict):
                continue
            if self._show_terminal_fields:
                try:
                    if not target or ssh_target(record) != target:
                        continue
                except ValueError:
                    continue
            self.ssh.addItem(
                f"{record.get('label', serial)} [{record.get('username', '')}@"
                f"{record.get('host', '')}] · {serial}", str(serial)
            )
        index = self.ssh.findData(selected) if selected else -1
        self.ssh.setCurrentIndex(max(0, index))

    def _validate_terminal_fields(self):
        terminal = self._metadata.get("terminal", {})
        if (not isinstance(terminal, dict) or type(terminal.get("schema_version", 1)) is not int
                or terminal.get("schema_version", 1) != 1):
            return False, "Unsupported terminal metadata; save refused to preserve it."
        target = self.target_server.currentData()
        record = self._ssh_records().get(self.ssh.currentData())
        if not isinstance(target, dict) or not isinstance(record, dict):
            return False, "Select a target server and a matching SSH profile."
        try:
            if ssh_target(record) != target:
                return False, "The selected SSH profile does not match the terminal target server."
        except ValueError as exc:
            return False, str(exc)
        return True, ""

    def _credential_editor(self):
        record = self._ssh_records().get(self.ssh.currentData())
        if not isinstance(record, dict):
            raise ValueError("Select an existing SSH registry profile.")
        editor = SSH(new_conn=False)
        editor._load_data(deepcopy(record))
        return editor

    def is_validated(self):
        if self._show_terminal_fields:
            ok, message = self._validate_terminal_fields()
            if not ok:
                return ok, message
        return self._validate_route()

    def _validate_route(self):
        if not self.label.text().strip():
            return False, "Label is required."
        if self.default_channel.currentText() != "outgoing.command":
            return False, "Matrix SSH requires the outgoing.command channel."
        ok, message = self._require_serial()
        if not ok:
            return ok, message
        try:
            editor = self._credential_editor()
        except ValueError as exc:
            return False, str(exc)
        try:
            return editor.is_validated()
        finally:
            editor.deleteLater()

    def is_connection(self):
        return True

    def deploy_fields(self):
        # Metadata is not runtime authority and never enters an agent config.
        ok, message = self._validate_route()
        if not ok:
            raise ValueError(message)
        editor = self._credential_editor()
        try:
            fields = editor.deploy_fields()
        finally:
            editor.deleteLater()
        fields.update(channel="outgoing.command",
                      default_outgoing=self.default_outgoing.isChecked())
        return fields
