from abc import ABC, abstractmethod

class BasePacket(ABC):
    @abstractmethod
    def is_valid(self) -> bool:
        pass

    @abstractmethod
    def set_data(self, data: dict):
        pass

    @abstractmethod
    def set_packet(self, packet):
        pass

    @abstractmethod
    def get_packet(self) -> dict:
        pass

    @abstractmethod
    def get_error_success(self) -> int:
        pass

    @abstractmethod
    def get_error_success_msg(self) -> str:
        pass