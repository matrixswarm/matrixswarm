"""Tests for reliable asynchronous Oracle query dispatch."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))

from core.python_core.agent_factory.oracle.oracle_query_mixin import (  # noqa: E402
    OracleQueryMixin,
)


class _Packet:
    def __init__(self):
        self.data = {}

    def set_data(self, data):
        self.data = data


class _OracleNode:
    @staticmethod
    def get_universal_id():
        return "oracle-1"


class _Agent(OracleQueryMixin):
    def __init__(self):
        self.command_line_args = {"universal_id": "detective-1"}
        self.results = []
        self.logs = []

    def get_nodes_by_role(self, role, return_count=1):
        return [_OracleNode()]

    def get_delivery_packet(self, packet_type):
        return _Packet()

    def pass_packet(self, packet, universal_id):
        content = packet.data["content"]
        self.cmd_oracle_response(
            {
                "query_id": content["query_id"],
                "response": '{"summary":"ok"}',
            },
            packet,
        )

    def receive(self, query, response, error=None):
        self.results.append((query.query_id, response, error))

    def log(self, message=None, **kwargs):
        self.logs.append(message or str(kwargs))


class OracleQueryMixinTests(unittest.TestCase):
    def test_synchronous_response_cannot_beat_query_cache(self):
        agent = _Agent()
        query = agent.get_oracle_query_object()
        query.response_handler = "receive"

        agent.send_to_oracle(query)

        self.assertEqual(
            [(query.query_id, '{"summary":"ok"}', None)],
            agent.results,
        )
        self.assertNotIn(query.query_id, agent._oracle_queries)


if __name__ == "__main__":
    unittest.main()
