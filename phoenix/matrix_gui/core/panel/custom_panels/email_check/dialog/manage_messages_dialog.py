# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QMessageBox, QCheckBox
)
from PyQt6.QtCore import Qt

class ManageMessagesDialog(QDialog):
    def __init__(self, parent=None, folder="INBOX", messages=None):
        super().__init__(parent)
        self.setWindowTitle(f"🗑 Manage Messages – {folder}")
        self.setMinimumSize(500, 400)
        self.selected_ids = []
        self.messages = messages or []

        layout = QVBoxLayout(self)
        self.label = QLabel("Select one or more messages to delete:")
        layout.addWidget(self.label)

        # message list
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for msg in self.messages:
            msg.get("timestamp", 0)
            size = msg.get("size", "?")
            uuid = msg.get("uuid", "")
            label = f"{msg.get('uid', '')[:6]} — {uuid[:8]} ({size} bytes)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, uuid)
            self.list.addItem(item)
        layout.addWidget(self.list)

        # buttons
        btns = QHBoxLayout()
        self.remote_cb = QCheckBox("Delete on imap server also")
        self.remote_cb.setChecked(False)
        btns.addWidget(self.remote_cb)

        self.btn_delete = QPushButton("🗑 Delete Selected")
        self.btn_cancel = QPushButton("Cancel")
        btns.addStretch()
        btns.addWidget(self.btn_delete)
        btns.addWidget(self.btn_cancel)
        layout.addLayout(btns)

        self.btn_delete.clicked.connect(self._confirm_delete)
        self.btn_cancel.clicked.connect(self.reject)

    def _confirm_delete(self):
        selected = self.list.selectedItems()
        if not selected:
            QMessageBox.information(self, "No Selection", "Select at least one message to delete.")
            return
        self.selected_ids = [i.data(Qt.ItemDataRole.UserRole) for i in selected]
        self.accept()
