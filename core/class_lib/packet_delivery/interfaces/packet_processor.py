from abc import ABC, abstractmethod
from typing import Dict, Any

class PacketProcessorBase(ABC):
    """Interface for all inbound packet processors (decrypt/plaintext/etc)."""

    @abstractmethod
    def prepare_for_processing(self, file_data: Dict[str, Any]) -> Dict[str, Any]:
        """Processes raw incoming file_data. Returns decrypted or parsed content."""
        pass


class PacketEncryptorBase(ABC):
    """Interface for all outbound encryption strategies."""

    @abstractmethod
    def prepare_for_delivery(self, packet_obj: Any) -> Dict[str, Any]:
        """Wraps packet_obj in encryption envelope. Returns safe dict to write."""
        pass