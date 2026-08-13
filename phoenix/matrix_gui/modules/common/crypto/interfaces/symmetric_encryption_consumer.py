from abc import ABC, abstractmethod

class SymmetricEncryptionConsumer(ABC):
    @abstractmethod
    def requires_symmetric_encryption(self) -> bool:
        """Return True if this agent should receive a symmetric AES key."""
        return False

    @abstractmethod
    def set_symmetric_key(self, symmetric_profile: dict):
        """Injects the symmetric encryption key profile (key, type, created_at)."""
        pass