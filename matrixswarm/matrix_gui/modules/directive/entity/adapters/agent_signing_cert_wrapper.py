from matrix_gui.modules.common.crypto.interfaces.signing_cert_consumer import SigningCertConsumer
from matrix_gui.modules.directive.entity.agent import Agent
class AgentSigningCertWrapper(SigningCertConsumer):
    def __init__(self, agent:Agent):
        self.agent = agent
        self._has_cert = False

    def get_serial(self):
        return self.agent.get_item('agent').get('serial',"")

    def requires_signing(self) -> bool:
        agent_tags = self.agent.get_item("agent").get("tags", {})
        packet_signing = agent_tags.get("packet_signing", {})
        return packet_signing.get("out", False)  # only mint if it signs anything

    def set_signing_cert(self, cert_profile: dict):
        """Injects the minted cert profile into the agent."""
        self.agent.add_item("signing_cert", cert_profile)
        self._has_cert = True
