"""Vault-backed encryption identity for durable agent state."""

from __future__ import annotations

import base64
import os
import re
import uuid
from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
)

from .base_editor import BaseEditor


_STATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class PersistentState(BaseEditor):
    """Generate once, retain in the Vault, and assign as a constraint."""

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, default_channel_options)

        self.label = QLineEdit(self.generate_default_label())
        self.state_id = QLineEdit(f"state-{uuid.uuid4().hex}")
        self.algorithm = QLineEdit("AES-256-GCM")
        self.algorithm.setReadOnly(True)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_version = QSpinBox()
        self.key_version.setRange(1, 2_147_483_647)
        self.key_version.setValue(1)
        self.created_at = QLineEdit(_utc_now())
        self.created_at.setReadOnly(True)
        self.rotated_at = QLineEdit("")
        self.rotated_at.setReadOnly(True)
        self.rotate_btn = QPushButton("♻️ Rotate Persistent-State Key")
        self.rotate_btn.clicked.connect(self._rotate_key)
        self.path_selector = QComboBox()
        self.path_selector.addItem("config/security/persistent_state")

        layout = QFormLayout(self)
        layout.addRow("Label", self.label)
        layout.addRow("Stable State ID", self.state_id)
        layout.addRow("Algorithm", self.algorithm)
        layout.addRow("AES Key", self.key)
        layout.addRow("Key Version", self.key_version)
        layout.addRow("Created (UTC)", self.created_at)
        layout.addRow("Last Rotated (UTC)", self.rotated_at)
        layout.addRow(self.rotate_btn)
        layout.addRow("Directive Path", self.path_selector)
        layout.addRow("Serial", self.serial)

        if new_conn:
            self._generate_key()

    def _lock_persisted_identity(self):
        self.state_id.setReadOnly(True)
        self.key.setReadOnly(True)
        self.key_version.setEnabled(False)
        self.rotate_btn.setEnabled(False)
        self.rotate_btn.setToolTip(
            "Rotation stays locked until journal re-encryption is available."
        )

    def _generate_key(self):
        self.key.setText(base64.b64encode(os.urandom(32)).decode("ascii"))

    def _rotate_key(self):
        answer = QMessageBox.question(
            self,
            "Rotate Persistent-State Key?",
            "Existing journal ciphertext cannot be opened with the new key "
            "until it has been migrated. Rotate this key now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._generate_key()
        self.key_version.setValue(self.key_version.value() + 1)
        self.rotated_at.setText(_utc_now())

    def on_load(self, data):
        self.label.setText(str(data.get("label", "")))
        self.state_id.setText(str(data.get("state_id", "")))
        self.algorithm.setText(str(data.get("algorithm", "AES-256-GCM")))
        self.key.setText(str(data.get("key", "")))
        self.key_version.setValue(int(data.get("key_version", 1)))
        self.created_at.setText(str(data.get("created_at", "")))
        self.rotated_at.setText(str(data.get("rotated_at", "")))
        self.path_selector.setCurrentText(
            str(data.get("node_directive_path", "config/security/persistent_state"))
        )
        self.serial.setText(str(data.get("serial", "")))
        self._lock_persisted_identity()

    def _state_fields(self):
        return {
            "state_id": self.state_id.text().strip(),
            "algorithm": self.algorithm.text().strip(),
            "key": self.key.text().strip(),
            "key_version": self.key_version.value(),
            "created_at": self.created_at.text().strip(),
            "rotated_at": self.rotated_at.text().strip(),
            "sensitive_fields": {"key": "1"},
        }

    def deploy_fields(self):
        return self._state_fields()

    def serialize(self):
        self._ensure_serial()
        return {
            "node_directive_path": self.path_selector.currentText().strip(),
            "serial": self.serial.text().strip(),
            "label": self.label.text().strip(),
            **self._state_fields(),
        }

    def is_validated(self):
        ok, message = self._require_serial()
        if not ok:
            return ok, message
        if not self.label.text().strip():
            return False, "Label is required."
        if not _STATE_ID.fullmatch(self.state_id.text().strip()):
            return (
                False,
                "State ID must contain only letters, numbers, dot, dash, or underscore.",
            )
        try:
            raw_key = base64.b64decode(self.key.text().strip(), validate=True)
        except Exception:
            return False, "AES key must be valid base64."
        if len(raw_key) != 32:
            return False, "Persistent-state keys must be exactly 256 bits."
        if not self.created_at.text().strip():
            return False, "Creation timestamp is required."
        return True, ""
