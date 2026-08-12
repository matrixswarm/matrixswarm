from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QPushButton, QHBoxLayout, QApplication, QScrollArea, QWidget
from PyQt6.QtCore import Qt
from functools import partial


class CertSetDialog(QDialog):
    def __init__(self, cert_set, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cert Set Viewer")
        self.setMinimumSize(700, 540)
        layout = QVBoxLayout(self)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        inner = QWidget()
        v_inner = QVBoxLayout(inner)

        for cert_path, pem in cert_set.items():
            # === Add spacing between blocks ===
            v_inner.addSpacing(14)

            # === Add bold label above text box ===
            label = QLabel(cert_path)
            label.setStyleSheet("font-weight: bold; padding-bottom: 2px;")
            v_inner.addWidget(label)

            row = QHBoxLayout()

            text = QTextEdit()
            text.setReadOnly(True)
            text.setText(pem)
            text.setFixedHeight(80 if pem else 20)
            row.addWidget(text, stretch=1)

            if "pubkey" in cert_path.lower() or "public" in cert_path.lower():
                copy_btn = QPushButton("Copy Pubkey")
                copy_btn.clicked.connect(partial(QApplication.clipboard().setText, pem))
                row.addWidget(copy_btn)

            v_inner.addLayout(row)

        inner.setLayout(v_inner)
        scroll.setWidget(inner)
        layout.addWidget(scroll)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)
