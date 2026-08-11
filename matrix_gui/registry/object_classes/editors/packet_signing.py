from .base_editor import BaseEditor
from PyQt6.QtWidgets import QComboBox
from matrix_gui.modules.vault.crypto.cert_factory import _generate_keypair

class PacketSigning(BaseEditor):
    """Commander Edition – autogen signing editor"""

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn)

        self.path_selector = QComboBox()
        #node directive path - add as you see fit
        self.path_selector.addItems([
            "config/security/signing", #default
            #"config/security/signing2",
        ])

        priv, pub, _ = _generate_keypair()
        remote_priv, remote_pub, _ = _generate_keypair()
        self.bundle = {
            "pubkey": pub,
            "privkey": priv,
            "remote_pubkey": remote_pub,
            "remote_privkey": remote_priv,
        }

    def get_deployment_path(self, universal_id):
        return ["certs", universal_id, "signing"]

    def on_load(self, data: dict):
        pass

    def is_autogen(self) -> bool:
        return True

    def deploy_fields(self):
        return self.bundle.copy()

    #when you don't want to export the whole bundle to the directive
    def directive_fields(self):
        # Extract only privkey and remote_pubkey
        #"sensitive" tells the agent returning the agent tree to phoenix not to include these fields
        return {
            "privkey": self.bundle["privkey"],
            "remote_pubkey": self.bundle["remote_pubkey"],
            "sensitive_fields": {"privkey": "1", "remote_pubkey": "1"},
        }

    def serialize(self):
        return {}

    def is_validated(self):
        return True
