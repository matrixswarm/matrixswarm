from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton
from PyQt5.QtCore import pyqtSignal


class VaultPasswordDialog(QDialog):
    password_entered = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔐 Vault Password")
        self.setFixedSize(320, 140)

        layout = QVBoxLayout()
        self.setLayout(layout)

        label = QLabel("Enter vault password:")
        label.setStyleSheet("color: lime;")
        layout.addWidget(label)

        self.input = QLineEdit()
        self.input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.input)

        self.unlock_button = QPushButton("Unlock")
        self.unlock_button.clicked.connect(self.handle_submit)
        layout.addWidget(self.unlock_button)

    def handle_submit(self):
        password = self.input.text().strip()
        if password:
            self.password_entered.emit(password)
            self.accept()
        else:
            self.reject()
