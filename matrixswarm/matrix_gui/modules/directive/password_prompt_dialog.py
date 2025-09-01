from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton

class PasswordPromptDialog(QDialog):
    def __init__(self, title="Enter Password", prompt="Provide password", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)

        self._visible = False
        self.password = ""

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(prompt))

        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Password)
        self.edit.setPlaceholderText("••••••••")
        row.addWidget(self.edit, 1)


        self.toggle_btn = QPushButton("👁")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setToolTip("Show/Hide password")
        self.toggle_btn.clicked.connect(self._toggle_echo)

        row.addWidget(self.toggle_btn, 0)

        layout.addLayout(row)

        btn_row = QHBoxLayout()

        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self._accept)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(self.ok_btn)
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row)

    def _toggle_echo(self):
        self._visible = self.toggle_btn.isChecked()

        self.edit.setEchoMode(QLineEdit.Normal if self._visible else QLineEdit.Password)
        self.toggle_btn.setText("🙈" if self._visible else "👁")

    def _accept(self):
        self.password = self.edit.text()
        self.accept()

    @staticmethod
    def get_password(parent=None, title="Enter Password", prompt="Provide password"):
        dlg = PasswordPromptDialog(title, prompt, parent)
        ok = (dlg.exec_() == dlg.Accepted)
        return (dlg.password, ok)
