from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel
)

class EncryptionStagingDialog(QDialog):
    def __init__(self, directive_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Directive Encryption Staging")
        self.setMinimumSize(800, 600)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Inspect the fully processed directive before encryption:"))

        self.editor = QTextEdit()
        self.editor.setPlainText(directive_text)
        self.editor.setReadOnly(True)
        layout.addWidget(self.editor)

        button_row = QHBoxLayout()
        self.encrypt_btn = QPushButton("Encrypt & Save")
        self.cancel_btn = QPushButton("Cancel")
        button_row.addWidget(self.encrypt_btn)
        button_row.addWidget(self.cancel_btn)

        layout.addLayout(button_row)

        self.encrypt_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

    def get_text(self):
        return self.editor.toPlainText()