# vault_init.py
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton

class VaultInitDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Initialize Vault")
        self.setFixedSize(300, 120)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("No vault found.\nWould you like to create one now?"))

        btn_create = QPushButton("✅ Create New Vault")
        btn_cancel = QPushButton("❌ Cancel")

        layout.addWidget(btn_create)
        layout.addWidget(btn_cancel)

        btn_create.clicked.connect(lambda: self.done(1))
        btn_cancel.clicked.connect(lambda: self.done(0))
