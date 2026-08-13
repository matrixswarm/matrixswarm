from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox
)
from PyQt6.QtCore import Qt
import json
from pathlib import Path

# commander systems
from .registry_singleton import RegistrySingleton
from .object_classes import EDITOR_REGISTRY


class ResourceManagerDialog(QDialog):
    """
    Commander Edition — Resource Manager.
    Handles CRUD + assignment of registry objects for a given class type.
    """

    def __init__(self, class_name: str, assign_callback=None, parent=None):
        super().__init__(parent)
        self.class_name = class_name
        self.assign_callback = assign_callback
        self.setWindowTitle(f"Resources – {class_name}")
        self.setMinimumSize(600, 400)

        self.reg = RegistrySingleton.get()
        self.items = []

        layout = QVBoxLayout(self)

        # Header
        title = QLabel(f"<b>{class_name}</b> resources")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # List
        self.list = QListWidget()
        layout.addWidget(self.list)

        # Buttons
        btn_row = QHBoxLayout()
        self.new_btn = QPushButton("New")
        self.edit_btn = QPushButton("Edit")
        self.delete_btn = QPushButton("Delete")
        self.assign_btn = QPushButton("Assign to Agent")

        btn_row.addWidget(self.new_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.assign_btn)
        layout.addLayout(btn_row)

        self.new_btn.clicked.connect(self._new)
        self.edit_btn.clicked.connect(self._edit)
        self.delete_btn.clicked.connect(self._delete)
        self.assign_btn.clicked.connect(self._assign)

        self._populate()

    # ---------------------------------------------------------
    def _populate(self):
        """Fill list with registry objects for this class."""
        self.list.clear()
        data = self.reg.get_namespace(self.class_name) or {}
        for serial, obj in data.items():
            label = obj.get("label") or serial
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, serial)
            valid = obj.get("validated", False)
            prefix = "✔️" if valid else "❗"
            item.setText(f"{prefix} {label}")
            self.list.addItem(item)
        print(f"[RESOURCES] Loaded {self.list.count()} {self.class_name} objects.")

    # ---------------------------------------------------------
    def _new(self):
        """Create a new registry object via editor."""
        editor_cls = EDITOR_REGISTRY.get(self.class_name)
        if not editor_cls:
            QMessageBox.warning(self, "Missing editor", f"No editor for {self.class_name}")
            return

        editor = editor_cls()
        if editor.exec():
            obj_data = editor.serialize()
            serial = obj_data.get("serial")
            self.reg.set(self.class_name, serial, obj_data)
            self._populate()

    # ---------------------------------------------------------
    def _edit(self):
        """Edit selected object."""
        item = self.list.currentItem()
        if not item:
            return
        serial = item.data(Qt.ItemDataRole.UserRole)
        obj = self.reg.get(self.class_name, serial)
        editor_cls = EDITOR_REGISTRY.get(self.class_name)
        if not obj or not editor_cls:
            QMessageBox.warning(self, "Missing editor", f"No editor for {self.class_name}")
            return

        editor = editor_cls()
        editor.on_load(obj["data"])
        if editor.exec():
            new_data = editor.serialize()
            self.reg.set(self.class_name, serial, new_data)
            self._populate()

    # ---------------------------------------------------------
    def _delete(self):
        """Delete selected object."""
        item = self.list.currentItem()
        if not item:
            return
        serial = item.data(Qt.ItemDataRole.UserRole)
        ok = QMessageBox.question(
            self, "Confirm Delete", f"Delete {self.class_name} resource {serial}?"
        )
        if ok == QMessageBox.StandardButton.Yes:
            self.reg.delete(self.class_name, serial)
            self._populate()

    # ---------------------------------------------------------
    def _assign(self):
        """Return selected serial to the calling constraint."""
        item = self.list.currentItem()
        if not item:
            QMessageBox.warning(self, "Select", "Select a resource to assign.")
            return
        serial = item.data(Qt.ItemDataRole.UserRole)
        if self.assign_callback:
            self.assign_callback(self.class_name, serial)
        self.accept()
