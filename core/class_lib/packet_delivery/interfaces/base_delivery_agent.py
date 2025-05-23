from abc import ABC, abstractmethod

class BaseDeliveryAgent(ABC):
    """Interface for all delivery agent implementations (filesystem, redis, etc)."""

    @abstractmethod
    def set_location(self, loc: dict):
        """Sets the base location (e.g., file path or Redis structure). Returns self."""
        pass

    @abstractmethod
    def set_address(self, ids: list):
        """Sets target agent universal_ids. Returns self."""
        pass

    @abstractmethod
    def set_packet(self, packet):
        """Attaches a packet (must implement BasePacket). Returns self."""
        pass

    @abstractmethod
    def set_drop_zone(self, drop: dict):
        """Sets the internal drop path (e.g., 'incoming', 'alert'). Returns self."""
        pass

    @abstractmethod
    def get_agent_type(self) -> str:
        """Returns the agent type as string: 'filesystem', 'redis', etc."""
        pass

    @abstractmethod
    def get_error_success(self) -> int:
        """Returns 0 if successful, 1 if error occurred."""
        pass

    @abstractmethod
    def get_error_success_msg(self) -> str:
        """Returns human-readable reason for last failure."""
        pass

    @abstractmethod
    def create_loc(self):
        """Creates base directories or Redis structures. Returns self."""
        pass

    @abstractmethod
    def deliver(self, create: bool = True):
        """Performs the delivery. Optionally creates structure. Returns self."""
        pass
