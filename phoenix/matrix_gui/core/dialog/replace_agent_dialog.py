# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog
)
import os

class ReplaceAgentDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("♻️ Replace Agent Source")
        self.resize(400, 150)
        self.file_path = None
        self.agent_name = None

        layout = QVBoxLayout(self)

        # File picker
        self.file_label = QLabel("No file selected")
        btn_pick = QPushButton("📂 Select Agent Source")
        btn_pick.clicked.connect(self._pick_file)

        row1 = QHBoxLayout()
        row1.addWidget(self.file_label)
        row1.addWidget(btn_pick)
        layout.addLayout(row1)

        # Buttons
        row2 = QHBoxLayout()
        btn_ok = QPushButton("Deploy")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        row2.addWidget(btn_ok)
        row2.addWidget(btn_cancel)
        layout.addLayout(row2)

    def _pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Agent Source", "", "Python (*.py);;All Files (*)")
        if not path:
            return
        self.file_path = path
        self.agent_name = os.path.splitext(os.path.basename(path))[0]
        self.file_label.setText(os.path.basename(path))

    def get_selection(self):
        """Return the chosen file and agent name."""
        return self.file_path, self.agent_name

