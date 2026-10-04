"""Operator-owned Terminal Mode configuration, separate from the dashboard."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from matrix_gui.core.event_bus import EventBus
from matrix_gui.core.panel.home.terminal_access_controls import TerminalAccessControls
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.registry.registry_manager import RegistryManagerDialog


class TerminalModeDialog(QDialog):
    def __init__(self, parent=None, *, vault_authority=None):
        super().__init__(parent)
        self.setWindowTitle("Terminal Mode")
        self.resize(980, 600)
        self.setMinimumWidth(760)
        self._vault_authority = vault_authority or VaultCoreSingleton.get()
        self._vault_authority.read()

        layout = QVBoxLayout(self)
        introduction = QLabel(
            "Choose the saved deployments and operations Phoenix Terminal may request. "
            "Open Phoenix Terminal separately when you are ready to approve a connection."
        )
        introduction.setWordWrap(True)
        introduction.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(introduction)
        self.controls = TerminalAccessControls(
            self, vault_authority=self._vault_authority, terminal_mode=True
        )
        layout.addWidget(self.controls)

        buttons = QHBoxLayout()
        self.routes_button = QPushButton("Matrix SSH routes…")
        self.routes_button.setToolTip("Edit the saved SSH routes and their fixed Terminal target metadata.")
        self.routes_button.clicked.connect(self.open_routes)
        buttons.addWidget(self.routes_button)
        buttons.addStretch()
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        EventBus.on("vault.closed", self._vault_closed)

    def open_routes(self):
        dialog = RegistryManagerDialog(self, class_lock="matrix_ssh", terminal_mode=True)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()
        self.controls.refresh_from_vault()

    def _vault_closed(self, **_):
        self.reject()

    def done(self, result):
        EventBus.off("vault.closed", self._vault_closed)
        super().done(result)
