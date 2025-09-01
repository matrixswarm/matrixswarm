from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QDialogButtonBox, QCheckBox, QLabel,
    QComboBox, QToolButton
)
from PyQt5.QtWidgets import QComboBox, QLineEdit
class DeployOptionsDialog(QDialog):
    def __init__(self, parent=None, hosts=None, manage_conn_cb=None, refresh_hosts_cb=None):
        super().__init__(parent)
        self.setWindowTitle("Directive Deployment Options")
        self.setMinimumWidth(420)

        self._manage_conn_cb = manage_conn_cb
        self._refresh_hosts_cb = refresh_hosts_cb

        self.clown_car_cb = QCheckBox("Embed agent sources (Clown Car)")
        self.clown_car_cb.setChecked(True)

        self.hashbang_cb = QCheckBox("Add hashbang")
        self.hashbang_cb.setChecked(True)

        self.preview_cb = QCheckBox("Preview directive before saving")
        self.preview_cb.setChecked(True)

        manage_btn = QToolButton()
        manage_btn.setText("⋯")  # small manage button
        manage_btn.setToolTip("Open Manage Connections")
        manage_btn.clicked.connect(self._manage_and_refresh)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(self.clown_car_cb)
        layout.addWidget(self.hashbang_cb)
        layout.addWidget(self.preview_cb)
        layout.addWidget(self.buttons)

        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

    def _manage_and_refresh(self):
        if callable(self._manage_conn_cb):
            self._manage_conn_cb()
        if callable(self._refresh_hosts_cb):
            hosts = list(dict.fromkeys(self._refresh_hosts_cb() or []))  # de-dupe, keep order

    def get_options(self):
        return {
            "clown_car": self.clown_car_cb.isChecked(),
            "hashbang": self.hashbang_cb.isChecked(),
            "preview": self.preview_cb.isChecked(),
        }