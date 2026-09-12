from urllib.parse import urlsplit

from PyQt6.QtWidgets import QLabel, QLineEdit, QMessageBox
from .base_editor import BaseEditor


class CryptoAlert(BaseEditor):
    def _build_form(self):
        self.api = QLineEdit(self.config.get("bitcoin_api_url", "https://blockstream.info/api"))
        self.alert_role = QLineEdit(self.config.get("alert_role", "hive.alert"))
        self.layout.addRow("Bitcoin Esplora API (HTTPS):", self.api)
        self.layout.addRow("Alert delivery role:", self.alert_role)
        note = QLabel(
            "Prices use Phemex's public spot WebSocket; no exchange keys needed.\n"
            "The explorer sees queried Bitcoin addresses. Use your own HTTPS Esplora for privacy.\n"
            "Assign a dedicated persistent_state registry profile to this agent.\n"
            "Create, edit, pause and delete watches in the live Crypto Watches panel.\n"
            "Endpoint changes take effect after redeployment/restart."
        )
        note.setWordWrap(True)
        self.layout.addRow(note)

    def _save(self):
        url = self.api.text().strip().rstrip("/")
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                     and not parsed.password and not parsed.query and not parsed.fragment)
        except ValueError:
            valid = False
        role = self.alert_role.text().strip()
        if not valid or not role:
            QMessageBox.warning(self, "Invalid configuration", "Enter an HTTPS Esplora API URL and an alert role.")
            return
        self.node.config.update(bitcoin_api_url=url, alert_role=role, exchange="phemex")
        self.node.mark_dirty()
        self.accept()
