from .base_editor import BaseEditor
from PyQt6.QtWidgets import QComboBox
from matrix_gui.modules.vault.crypto.cert_factory import (
    _generate_root_ca, _generate_signed_cert, spki_pin_from_pem
)
from cryptography import x509

class ConnectionCert(BaseEditor):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent, new_conn)

        self._is_valid = False
        try:

            self.path_selector = QComboBox()
            # node directive path - add as you see fit
            self.path_selector.addItems([
                "config/security/connection",  # default
                # "config/imap_bk",
                # "config/imap_legacy",
                # "config/mail"
            ])

            tag = self.__class__.__name__.lower()
            ca_cert_pem, ca_key_pem, ca_key_obj = _generate_root_ca(f"{tag}_ca")
            issuer_cert = x509.load_pem_x509_certificate(ca_cert_pem.encode())
            server_cert_pem, server_key_pem, _ = _generate_signed_cert(
                common_name=f"{tag}_server", sans=[], issuer_cert=issuer_cert, issuer_key=ca_key_obj)
            client_cert_pem, client_key_pem, _ = _generate_signed_cert(
                common_name=f"{tag}_client", sans=[], issuer_cert=issuer_cert, issuer_key=ca_key_obj)
            self.bundle  = {
                "server_cert": {"cert": server_cert_pem, "key": server_key_pem, "spki_pin": spki_pin_from_pem(server_cert_pem)},
                "client_cert": {"cert": client_cert_pem, "key": client_key_pem, "spki_pin": spki_pin_from_pem(client_cert_pem)},
                "ca_root": {"cert": ca_cert_pem, "key": ca_key_pem},
                "sensitive_fields": {"server_cert": "1", "client_cert": "1", "ca_root": "1"},
            }
            self._is_valid = True
        except Exception as e:
            pass

    def on_load(self, data: dict):
        pass

    def get_deployment_path(self, universal_id):
        return ["certs", universal_id, "connection_cert"]

    def serialize(self):
        return {}

    def is_autogen(self) -> bool:
        return True

    def deploy_fields(self):
        return self.bundle.copy()

    def is_validated(self):
        return self._is_valid