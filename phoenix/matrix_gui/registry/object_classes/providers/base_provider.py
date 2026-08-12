from abc import ABC, abstractmethod

class ConnectionProvider(ABC):
    """
    Provider is responsible for:
    - Table column definitions
    - How a row is displayed
    - How conn_id is chosen
    """

    @abstractmethod
    def get_columns(self) -> list[str]:
        pass

    @abstractmethod
    def get_row(self, data: dict) -> list[str]:
        pass

    @abstractmethod
    def get_conn_id(self, conn_id: str, data: dict) -> str:
        pass

    @abstractmethod
    def get_default_channel_options(self) -> list[str]:
        """Return allowed default channels for this protocol."""
        pass