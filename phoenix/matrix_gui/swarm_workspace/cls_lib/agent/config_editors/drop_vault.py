"""Operator guidance for the dedicated persistent-state assignment."""
from PyQt6.QtWidgets import QLabel
from .base_editor import BaseEditor


class DropVault(BaseEditor):
    def _build_form(self):
        note = QLabel(
            "Drop Vault is a shared traveling clipboard for connected Phoenix operators.\n\n"
            "Assign a NEW, dedicated persistent_state Registry record to this agent, just like Crypto Alert. "
            "Keep that same record and universe on redeployment to keep access to stored drops. "
            "Do not reuse Crypto Alert's state identity/key or run two Drop Vault agents with one state identity.\n\n"
            "The live Drop Vault panel uploads pasted text or files, polls the listing, retrieves, copies, "
            "exports and deletes items. All authorized operators connected to this swarm can use it.\n\n"
            "Small files and pasted text only: 1 MiB/object, 256 MiB and 1000 objects/inbox, four simultaneous uploads. "
            "Uploads expire after five idle minutes. No content is executed.\n\n"
            "Keep a secure backup of the Registry persistent_state key; losing it loses the stored data."
        )
        note.setWordWrap(True)
        self.layout.addRow(note)

    def _save(self):
        self.accept()  # No credentials or live objects belong in deployment config.
