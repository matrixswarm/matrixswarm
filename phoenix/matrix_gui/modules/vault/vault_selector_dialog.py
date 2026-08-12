from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QLabel


class VaultSelectorDialog(QDialog):
    """First dialog user sees: choose Unlock, Create, Change PW."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vault Options")
        self.setFixedSize(320, 200)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Choose an action for your Vault:"))

        self.unlock_btn = QPushButton("🔓 Unlock Existing Vault")
        self.create_btn = QPushButton("🆕 Create New Vault")
        self.change_btn = QPushButton("🔑 Change Vault Password")
        self.cancel_btn = QPushButton("❌ Cancel")

        layout.addWidget(self.unlock_btn)
        layout.addWidget(self.create_btn)
        layout.addWidget(self.change_btn)
        layout.addWidget(self.cancel_btn)

        self.unlock_btn.clicked.connect(lambda: self._select("unlock"))
        self.create_btn.clicked.connect(lambda: self._select("create"))
        self.change_btn.clicked.connect(lambda: self._select("change"))
        self.cancel_btn.clicked.connect(self.reject)

        self.selection = None

    def _select(self, choice):
        self.selection = choice
        self.accept()
