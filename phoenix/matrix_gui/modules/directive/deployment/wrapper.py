import hashlib
import uuid
import time
from matrix_gui.modules.directive.entity.agent import Agent
from matrix_gui.modules.directive.aggregator.agent import AgentAggregator
from matrix_gui.modules.directive.entity.adapters.agent_connection_wrapper import AgentConnectionWrapper
from matrix_gui.modules.directive.entity.adapters.agent_cert_wrapper import AgentCertWrapper
from matrix_gui.modules.directive.entity.adapters.agent_signing_cert_wrapper import AgentSigningCertWrapper
from matrix_gui.modules.directive.entity.adapters.agent_directive_wrapper import AgentDirectiveWrapper
from matrix_gui.modules.directive.entity.adapters.agent_symmetric_key_wrapper import AgentSymmetricKeyWrapper

def agent_aggregator_wrapper(template):
    aa = AgentAggregator()

    def recurse(node, parent=None):
        a = Agent()
        a.add_item("agent", {
            "universal_id": node.get("universal_id"),
            "serial": str(hashlib.sha256(f"{uuid.uuid4()}-{time.time()}".encode()).hexdigest()),
            "name": node.get("name"),
            "tags": node.get("tags", {}),
            "config": node.get("config", {}),
            "children": [c.get("universal_id") for c in node.get("children", [])]
        })

        aa.add_agent(a)

        for child in node.get("children", []):
            recurse(child, parent=a)

    recurse(template)
    return aa

def agent_connection_wrapper(agent_aggregator):
    """Wraps each Agent in an AgentConnectionWrapper for connection matching."""
    wrapped = []

    for agent in agent_aggregator.get_agents():
        wrapper = AgentConnectionWrapper(agent)
        wrapped.append(wrapper)

    return wrapped

def agent_cert_wrapper(agent_aggregator):
    """Wraps each Agent in an AgentConnectionWrapper for connection matching."""
    wrapped = []

    for agent in agent_aggregator.get_agents():
        wrapper = AgentCertWrapper(agent)
        wrapped.append(wrapper)

    return wrapped

def agent_signing_cert_wrapper(agent_aggregator):
    """Wraps each Agent in an AgentConnectionWrapper for connection matching."""
    wrapped = []

    for agent in agent_aggregator.get_agents():
        wrapper = AgentSigningCertWrapper(agent)
        wrapped.append(wrapper)

    return wrapped

def agent_directive_wrapper(agent_aggregator):
    """Wraps each Agent in an AgentConnectionWrapper for connection matching."""
    wrapped = []

    for agent in agent_aggregator.get_agents():
        wrapper = AgentDirectiveWrapper(agent)
        wrapped.append(wrapper)

    return wrapped

def agent_symmetric_encryption_wrapper(agent_aggregator):
    wrapped = []

    for agent in agent_aggregator.get_agents():
        wrapper = AgentSymmetricKeyWrapper(agent)
        wrapped.append(wrapper)

    return wrapped