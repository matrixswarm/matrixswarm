from abc import ABC, abstractmethod

class SigningCertConsumer(ABC):
    @abstractmethod
    def requires_signing(self) -> bool:
        """Return True if this agent should receive a signing cert."""
        return False

    @abstractmethod
    def set_signing_cert(self, cert_profile: dict):
        """Injects the signing cert profile (pubkey, privkey, remote_pubkey)."""
        pass
