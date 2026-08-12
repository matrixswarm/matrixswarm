import os, base64
from datetime import datetime

class AutogenConstraintHandler:
    """
    Autogen constraints (packet_signing, symmetric_encryption, connection_cert)
    now produce Phoenix-style bundles.
    """

    def __init__(self, cls_name):
        self.cls_name = cls_name

    def resolve(self, constraint, agent, session):
        # Packet signing bundle
        if self.cls_name == "packet_signing":
            secret = base64.b64encode(os.urandom(24)).decode()
            full = {
                "remote_pubkey": secret,
                "remote_privkey": secret,
                "pubkey": secret,
                "privkey": secret
            }
            slice_ = {
                "remote_pubkey": secret
            }
            return {
                "category": "signing",
                "full": full,
                "slice": slice_
            }

        # Symmetric AES bundle
        if self.cls_name == "symmetric_encryption":
            key = base64.b64encode(os.urandom(32)).decode()
            full = {
                "key": key,
                "type": "aes",
                "created_at": datetime.utcnow().isoformat() + "Z"
            }
            slice_ = {
                "key": key,
                "type": "aes"
            }
            return {
                "category": "symmetric_encryption",
                "full": full,
                "slice": slice_
            }

        # Generic autogen fallback
        secret = base64.b64encode(os.urandom(24)).decode()
        return {
            "category": "connection",
            "full": {"generated": secret},
            "slice": {"public": secret}
        }
