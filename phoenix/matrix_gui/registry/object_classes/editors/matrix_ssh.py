"""Matrix SSH route composed with a reusable SSH registry credential."""
from copy import deepcopy

from PyQt6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLineEdit
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from .base_editor import BaseEditor
from .ssh import SSH


class MatrixSSH(BaseEditor):
    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, default_channel_options)
        self.label = QLineEdit(self.generate_default_label())
        self.ssh = QComboBox()
        self.ssh.addItem("Select SSH…", None)
        for serial, record in self._ssh_records().items():
            if isinstance(record, dict):
                self.ssh.addItem(
                    f"{record.get('label', serial)} [{record.get('username', '')}@"
                    f"{record.get('host', '')}] · {serial}", str(serial)
                )
        self.default_channel = QComboBox()
        self.default_channel.addItem("outgoing.command")
        self.default_outgoing = QCheckBox("Primary Outgoing Transport")
        self.path_selector = QComboBox()
        self.path_selector.addItem("config")
        layout = QFormLayout(self)
        layout.addRow("Label", self.label)
        layout.addRow("SSH Profile", self.ssh)
        layout.addRow("Channel", self.default_channel)
        layout.addRow("", self.default_outgoing)
        layout.addRow("Serial", self.serial)

    @staticmethod
    def _ssh_records():
        return VaultCoreSingleton.get().get_store("registry").get_namespace("ssh")

    def on_load(self, data):
        self.label.setText(str(data.get("label", "")))
        self.serial.setText(str(data.get("serial", "")))
        selected = str(data.get("ssh_serial", ""))
        index = self.ssh.findData(selected)
        if index < 0 and selected:
            self.ssh.addItem(f"Missing SSH profile · {selected}", selected)
            index = self.ssh.count() - 1
        self.ssh.setCurrentIndex(max(0, index))
        channel = data.get("channel", "outgoing.command")
        if self.default_channel.findText(str(channel)) < 0:
            self.default_channel.addItem(str(channel))
        self.default_channel.setCurrentText(str(channel))
        self.default_outgoing.setChecked(data.get("default_outgoing") is True)

    def serialize(self):
        self._ensure_serial()
        return {
            "label": self.label.text().strip(),
            "serial": self.serial.text().strip(),
            "ssh_serial": self.ssh.currentData(),
            "channel": self.default_channel.currentText(),
            "default_outgoing": self.default_outgoing.isChecked(),
            "node_directive_path": "config",
        }

    def _credential_editor(self):
        record = self._ssh_records().get(self.ssh.currentData())
        if not isinstance(record, dict):
            raise ValueError("Select an existing SSH registry profile.")
        editor = SSH(new_conn=False)
        editor._load_data(deepcopy(record))
        return editor

    def is_validated(self):
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
        ok, message = self.is_validated()
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
