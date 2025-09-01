from abc import ABC, abstractmethod
from typing import Union
class ConnectionConsumer(ABC):
    def __init__(self):
        self._has_connection = False

    @abstractmethod
    def has_connection(self) -> bool:
        pass

    @abstractmethod
    def get_requested_proto(self) -> Union[str, None]:
        pass

    @abstractmethod
    def accept_connection(self, connection: dict) -> None:
        """
        Finalizes connection assignment. Consumes a full connection object
        and applies it to the underlying system (e.g., agent).
        """
        pass