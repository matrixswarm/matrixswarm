from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QPushButton, QHBoxLayout, QApplication
from PyQt6.QtGui import QFont

class DeploymentDialog(QDialog):
    def __init__(self, command_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Deployment Ready")
        self.setMinimumSize(720, 320)

        layout = QVBoxLayout(self)

        label = QLabel("\ud83d\ude80 Your directive has been encrypted and saved.\n\nTo deploy from the command line, run:")
        label.setWordWrap(True)
        layout.addWidget(label)

        self.text_box = QTextEdit()
        self.text_box.setPlainText(command_text)
        self.text_box.setReadOnly(True)
        self.text_box.setFont(QFont("Courier New", 10))
        self.text_box.setMinimumHeight(180)
        layout.addWidget(self.text_box)

        btn_row = QHBoxLayout()

        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(command_text))
        btn_row.addWidget(self.copy_btn)

        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(self.ok_btn)

        layout.addLayout(btn_row)
