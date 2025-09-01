from typing import Union
from .interfaces.connection_consumer import ConnectionConsumer
class Connection:
    def __init__(self):
        self._item = None

    def set_connection_consumer(self, connection_consumer: ConnectionConsumer ):
        self._item = connection_consumer

    def has_connection(self) -> bool:
        return self._item and bool(self._item.has_connection())