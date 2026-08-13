from matrix_gui.modules.common.crypto.interfaces.cert_consumer import CertConsumer
from matrix_gui.modules.directive.entity.agent import Agent
class AgentCertWrapper(CertConsumer):
    def __init__(self, agent:Agent):
        self.agent = agent
        self._has_cert = False


    def requires_cert(self) -> bool:
        conn = self.agent.get_item("connection")
        proto = conn.get("proto", "") if conn else ""
        return proto in ("https", "wss")

    def get_cert_tag(self) -> str:
        conn = self.agent.get_item("connection")
        proto = conn.get("proto", "") if conn else ""
        return f"{proto}_{self.agent.universal_id}" if proto else self.agent.universal_id

    def use_sans(self) -> bool:
        """Whether SANs should be included. For HTTPS/WSS, yes."""
        return True

    def get_sans(self) -> dict:
        conn = self.agent.get_item("connection")
        if not conn or "host" not in conn:
            return {}
        host = conn["host"]
        is_ip = host.replace(".", "").isdigit()
        return {
            "ip": [host] if is_ip else [],
            "dns": [host] if not is_ip else []
        }

    def get_cert_algorithm(self) -> str:
        return "rsa"

    def get_key_size(self) -> int:
        return 2048

    def get_cert_validity_days(self) -> int:
        return 365

    def get_usage_profile(self) -> str:
        return "server"

    def set_cert(self, cert: dict) -> None:
        """Injects the minted cert profile into the agent."""
        self.agent.add_item("connection_cert", cert)
        self._has_cert = True
