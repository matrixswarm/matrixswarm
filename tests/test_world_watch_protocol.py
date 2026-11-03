"""Focused agents exercise collection, Oracle transport, alerts, and protected snapshot RPC."""
import json
from unittest.mock import Mock, patch
import unittest
import test_life_signal_protocol as fixture
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from promise_keeper.promise_keeper import Agent as PromiseAgent
from change_of_fortune.change_of_fortune import Agent as FortuneAgent
from oracle.prompt_assembly import PromptAssembly

class WatchProtocolTests(unittest.TestCase):
    def setUp(self):
        fixture.LifeSignalProtocolTests.setUp(self)

    def test_focused_agents_collect_analyze_and_dispatch(self):
        for cls in (PromiseAgent, FortuneAgent):
            with self.subTest(agent=cls):
                self.setUp()
                self.agent.__class__ = cls
                self.agent.engine = cls.ENGINE_CLASS(lambda doc: None)
                self.agent.engine.replace([self.source], 0)
                endpoint = Mock(); endpoint.get_universal_id.return_value = 'oracle'; endpoint.get_handler.return_value = 'cmd_alert'
                self.agent.get_nodes_by_role.return_value = [endpoint]
                with patch('life_signal.life_signal.collector.get', side_effect=[b'<title>Title</title><p>Old release</p>', b'<title>Title</title><p>New release</p>']):
                    self.assertTrue(self.agent._collect(self.source))
                    self.assertTrue(self.agent._collect(self.source))
                query = next(iter(self.agent.engine.queue()))
                self.agent._send_oracle()
                parts = [c.args[0].get_packet()['content'] for c in self.agent.pass_packet.call_args_list]
                assembly = PromptAssembly()
                raw = None
                for part in parts:
                    raw = assembly.accept('life-one', part) or raw
                request = raw
                self.assertIn('New release', request['messages'][1]['content'])
                self.assertIn('keywords', request['messages'][1]['content'])
                self.agent.cmd_oracle_response({'query_id': query, 'response': '{"match":true,"summary":"New release announced"}'}, None, IdentityObject(True, 'oracle'))
                self.agent.pass_packet.reset_mock()
                self.agent._dispatch()
                self.assertTrue(self.agent.pass_packet.called)
                self.assertIn('New release announced', str(self.agent.pass_packet.call_args.args[0].get_packet()))

    def test_capture_command_requires_verified_matrix(self):
        self.agent.__class__ = PromiseAgent
        self.agent.engine = PromiseAgent.ENGINE_CLASS(lambda doc: None)
        self.agent.engine.replace([self.source], 0)
        self.agent.engine.record_observation('one', 'private snapshot', self.source['url'], 'Title')
        capture = self.agent.engine.panel_snapshot()['captures'][0]['id']
        request = dict(self.request, capture_id=capture, offset=0)
        self.agent.cmd_get_capture(request, None, IdentityObject(True, 'stranger'))
        self.agent.crypto_reply.assert_not_called()
        self.agent.cmd_get_capture(request, None, IdentityObject(True, 'matrix'))
        self.assertEqual(self.agent.crypto_reply.call_args.kwargs['payload']['chunk'], 'private snapshot')

if __name__ == '__main__': unittest.main()
