from abc import ABC, abstractmethod
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet

class BaseConnector(ABC):
    """
    Standard interface for all connectors (HTTPS, WSS, Discord, etc).
    Ensures each connector can send data and be closed cleanly.
    """

    def __init__(self, session_id, agent, deployment):
        self.session_id = session_id
        self.agent = agent
        self.deployment = deployment
        self._status = "disconnected"
        self._channel_name = None

    @abstractmethod
    def send(self, packet:Packet, timeout=10):
        """Send a payload through this connector."""
        pass

    @abstractmethod
    def close(self, session_id: str = None, channel_name: str = None):
        """Close down the connector cleanly (terminate sockets, threads, etc)."""
        pass

    def get_status(self):
        return self._status

    def get_channel_name(self):
        return self._channel_name

    def _set_status(self, status):
        self._status = status

    def _set_channel_name(self, name):
        self._channel_name = name