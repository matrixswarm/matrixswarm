# matrix_gui/modules/vault/ui/dump_vault_popup.py
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QApplication
)
from PyQt6.QtCore import Qt

class DumpVaultPopup(QDialog):
    def __init__(self, vault_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔐 Vault Dump")
        self.resize(700, 500)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        layout = QVBoxLayout(self)

        # --- Text area ---
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(vault_text)
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        self.btn_select_all = QPushButton("Select All")
        self.btn_copy = QPushButton("Copy")
        self.btn_close = QPushButton("Close")

        self.btn_select_all.clicked.connect(self.text_edit.selectAll)
        self.btn_copy.clicked.connect(self.copy_to_clipboard)
        self.btn_close.clicked.connect(self.close)

        btn_row.addStretch()
        btn_row.addWidget(self.btn_select_all)
        btn_row.addWidget(self.btn_copy)
        btn_row.addWidget(self.btn_close)

        layout.addLayout(btn_row)

    def copy_to_clipboard(self):
        text = self.text_edit.toPlainText()
        QApplication.clipboard().setText(text)
