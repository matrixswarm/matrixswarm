# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
import json
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QTextEdit, QPushButton, QMessageBox
)

class RegistryObjectEditor(QDialog):
    """
    Edit (namespace.key) entries in the Registry.
    Object schema is free-form JSON for maximum flexibility.
    """
    def __init__(self, namespace, key=None, obj=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Registry Entry ({namespace})")
        self.namespace = namespace
        self.key = key
        self.obj = obj or {}

        layout = QFormLayout(self)

        # key (required)
        self.key_edit = QLineEdit(key or "")
        layout.addRow("Key", self.key_edit)

        # label (recommended)
        self.label_edit = QLineEdit(self.obj.get("label", ""))
        layout.addRow("Label", self.label_edit)

        # type (free form)
        self.type_edit = QLineEdit(self.obj.get("type", "generic"))
        layout.addRow("Type", self.type_edit)

        # data JSON object
        self.data_edit = QTextEdit()
        if "data" in self.obj:
            try:
                self.data_edit.setPlainText(json.dumps(self.obj["data"], indent=2))
            except Exception:
                self.data_edit.setPlainText(str(self.obj["data"]))
        layout.addRow("Data (JSON)", self.data_edit)

        # Save
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        layout.addRow(save_btn)

    def _save(self):
        key = self.key_edit.text().strip()
        if not key:
            QMessageBox.warning(self, "Error", "Key is required.")
            return

        label = self.label_edit.text().strip()
        type_ = self.type_edit.text().strip() or "generic"

        # parse JSON
        try:
            data = json.loads(self.data_edit.toPlainText() or "{}")
        except Exception:
            QMessageBox.warning(self, "Error", "Invalid JSON in Data field.")
            return

        self.key = key
        self.obj = {"label": label, "type": type_, "data": data}
        self.accept()

    def serialize(self):
        return self.key, self.obj
