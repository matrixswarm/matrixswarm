from abc import ABC, abstractmethod

class CertConsumer(ABC):
    def __init__(self):
        self._has_connection = False

    @abstractmethod
    def requires_cert(self) -> bool:
        """Return True if this consumer needs a cert issued."""
        return False

    @abstractmethod
    def get_cert_tag(self) -> str:
        """Returns a unique tag for the cert, e.g., 'https_matrix-https'."""
        pass

    @abstractmethod
    def use_sans(self) -> bool:
        """Whether to include subject alternative names (IP/DNS)."""
        return True

    @abstractmethod
    def get_sans(self) -> dict:
        """Returns a dict like {'ip': ['1.2.3.4'], 'dns': ['my.domain.com']}"""
        return {}

    @abstractmethod
    def get_cert_algorithm(self) -> str:
        """Return 'rsa' or 'ec'."""
        return "rsa"

    @abstractmethod
    def get_key_size(self) -> int:
        return 2048

    @abstractmethod
    def get_cert_validity_days(self) -> int:
        return 365

    @abstractmethod
    def get_usage_profile(self) -> str:
        """Return 'server', 'client', or 'both'."""
        return "server"

    @abstractmethod
    def set_cert(self, cert: dict) -> None:
        """Injects the finalized cert profile into the system (e.g., agent)."""
        pass
