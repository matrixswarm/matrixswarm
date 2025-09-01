from matrix_gui.modules.directive.entity.interfaces.connection_consumer import ConnectionConsumer
from typing import Union
from matrix_gui.modules.directive.entity.agent import Agent
class AgentConnectionWrapper(ConnectionConsumer):
    def __init__(self, agent:Agent):
        super().__init__()
        self.agent = agent  # Agent instance

    def has_connection(self) -> bool:
        conn = self.agent.get_item("connection")
        return bool(conn and isinstance(conn, dict) and "proto" in conn)

    def get_requested_proto(self) ->Union[str, None]:
        # First check if already injected
        conn = self.agent.get_item("connection")
        if conn and "proto" in conn:
            return conn["proto"]

        # Look under tags → connection → proto
        tags = self.agent.get_item("agent").get("tags", {})
        conn_tag = tags.get("connection", {})
        if isinstance(conn_tag, dict) and "proto" in conn_tag:
            return conn_tag["proto"]

        return None

    def get_universal_id(self) -> str:
        return self.agent.universal_id

    def get_name(self) -> str:
        return self.agent.name

    def accept_connection(self, connection: dict) -> None:
        self.agent.add_item("connection", connection)
        self._has_connection = True