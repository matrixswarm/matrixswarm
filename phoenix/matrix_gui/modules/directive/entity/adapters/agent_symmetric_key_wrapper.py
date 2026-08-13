# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
from matrix_gui.modules.common.crypto.interfaces.symmetric_encryption_consumer import SymmetricEncryptionConsumer
from matrix_gui.modules.directive.entity.agent import Agent

class AgentSymmetricKeyWrapper(SymmetricEncryptionConsumer):
    def __init__(self, agent: Agent):
        self.agent = agent
        self._has_key = False

    def requires_symmetric_encryption(self) -> bool:
        """Checks agent tags for symmetric_encryption key request."""
        agent_tags = self.agent.get_item("agent").get("tags", {})
        symmetric_tag = agent_tags.get("symmetric_encryption", {})
        return bool(symmetric_tag)  # any symmetric_encryption tag means it wants a key

    def set_symmetric_key(self, symmetric_profile: dict):
        """Inject the AES key profile into the agent config."""

        self.agent.add_item("symmetric_encryption", symmetric_profile)
        self._has_key = True

    def has_key(self) -> bool:
        return self._has_key
