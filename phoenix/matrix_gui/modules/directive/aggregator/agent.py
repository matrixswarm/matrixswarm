from typing import Union
from matrix_gui.modules.directive.entity.agent import Agent
class AgentAggregator:
    def __init__(self):
        self._agents = {}

    def add_agent(self, agent: Agent):
        if not isinstance(agent, Agent):
            raise TypeError("Only Agent instances may be added")

        uid = agent.universal_id
        if not uid or not isinstance(uid, str):
            raise ValueError("Agent must have a valid 'universal_id' string")

        if uid in self._agents:
            raise ValueError(f"Duplicate universal_id '{uid}' not allowed")

        self._agents[uid] = agent

    def get_agent(self, universal_id: str) -> Union[Agent, None]:
        return self._agents.get(universal_id)

    def get_agents(self) -> list[Agent]:
        return list(self._agents.values())

    def has_agent(self, universal_id: str) -> bool:
        return universal_id in self._agents

    def count(self) -> int:
        return len(self._agents)
