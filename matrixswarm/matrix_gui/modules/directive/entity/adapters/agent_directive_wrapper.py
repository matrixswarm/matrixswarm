from matrix_gui.modules.directive.entity.agent import Agent
class AgentDirectiveWrapper:

    def __init__(self, agent: Agent):
        self.agent = agent

    def uid(self) -> str:
        return self.agent.universal_id

    def get_serial(self):
        return self.agent.get_item('agent').get('serial',"")

    def name(self) -> str:
        return self.agent.name

    def tags(self) -> dict:
        return self.agent.get_item("agent").get("tags", {})

    def has_packet_signing(self) -> bool:
        return any(self.tags().get("packet_signing", {}).values())

    def get_signing(self) -> dict:
        return self.agent.get_item("signing_cert") or {}

    def get_connection_cert(self) -> dict:
        return self.agent.get_item("connection_cert") or {}

    def get_connection(self) -> dict:
        return self.agent.get_item("connection") or {}

    def get_proto(self) -> str | None:
        return self.tags().get("connection", {}).get("proto")

    def get_security_tag(self) -> str | None:
        proto = self.get_proto()
        if proto:
            return f"perimeter_{proto}"
        return None

    def get_config_overrides(self) -> dict:
        connection = self.agent.get_item("connection") or {}
        port = connection.get("port")
        allowlist_ips = connection.get("allowlist_ips") or []

        overrides = {}
        if port is not None:
            overrides["port"] = port
        if allowlist_ips:
            # only inject if non-empty list
            overrides["allowlist_ips"] = allowlist_ips
        return overrides

    def get_connection_snapshot(self) -> dict:
        return self.agent.get_item("connection") or {}