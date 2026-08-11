import os, base64
from .base_editor import BaseEditor
from PyQt6.QtWidgets import QComboBox

class SymmetricEncryption(BaseEditor):
    """Commander Edition – autogen symmetric AES key editor"""

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn)

        self.path_selector = QComboBox()
        # node directive path - add as you see fit
        self.path_selector.addItems([
            "config/security/symmetric_encryption",  # default
        ])

        self.bundle = {
            "key": base64.b64encode(os.urandom(32)).decode(),
            "type": "aes",
            "sensitive_fields": {"key": "1"},
        }

    def get_deployment_path(self, universal_id):
        return ["certs", universal_id, "symmetric_encryption"]


    def on_load(self, data: dict):
        pass

    def is_autogen(self) -> bool:
        return True

    def deploy_fields(self):
        return self.bundle.copy()

    def serialize(self):
        return {}

    def is_validated(self):
        return True
