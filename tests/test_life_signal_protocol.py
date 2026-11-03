"""Protocol, Oracle and relay integration without live services."""
import os
import base64
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'matrixos'))
sys.path.insert(0, str(ROOT / 'matrixos' / 'agents' / 'python_core'))
os.environ.setdefault('SITE_ROOT', str(ROOT / 'matrixos'))
os.environ.setdefault('AGENT_PATH', str(ROOT / 'matrixos' / 'agents' / 'python_core'))
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from core.python_core.class_lib.packet_delivery.packet.standard.command.packet import Packet as Command
from core.python_core.class_lib.packet_delivery.packet.notify.alert.general import Packet as Notice
from life_signal.engine import LifeSignalEngine
from life_signal.life_signal import Agent
from life_signal.sources import Challenge
from oracle.prompt_assembly import PromptAssembly
from core.python_core.class_lib.packet_delivery.utility.security.packet_size import guard_packet_size


class LifeSignalProtocolTests(unittest.TestCase):
    def setUp(self):
        self.agent = object.__new__(Agent)
        self.agent.command_line_args = {'universal_id': 'life-one'}
        self.agent.get_matrix_universal_id = lambda: 'matrix'
        self.agent.rpc_role = 'hive.rpc'; self.agent.oracle_role = 'hive.oracle'
        self.agent.engine = LifeSignalEngine(lambda doc: None)
        self.agent.crypto_reply = Mock(); self.agent.log = Mock()
        self.agent.get_nodes_by_role = Mock(return_value=[])
        self.agent.get_delivery_packet = lambda name: Notice() if name == 'notify.alert.general' else Command()
        self.agent.pass_packet = Mock(return_value=True)
        self.agent._next_checks = {}
        self.agent._scheduled_sources = {}
        self.agent._source_lock = threading.RLock()
        self.source = {'id': 'one', 'name': 'News', 'url': 'https://example.com/news',
            'kind': 'page', 'keywords': ['Jane'], 'interval_sec': 3600,
            'alert_role': 'hive.alert', 'enabled': True}
        self.agent.engine.replace([self.source], 0)
        self.source = self.agent.engine.snapshot()['sources'][0]
        self.request = {'target_universal_id': 'life-one', 'session_id': 'session',
                        'token': 'token', 'request_id': 'request', 'sources': [], 'revision': 1}

    def test_configuration_requires_verified_matrix_and_exact_target(self):
        for identity in (None, IdentityObject(False, 'matrix'), IdentityObject(True, 'other')):
            self.agent.cmd_update_sources(self.request, None, identity)
        self.agent.cmd_update_sources(dict(self.request, target_universal_id='wrong'), None, IdentityObject(True, 'matrix'))
        self.agent.crypto_reply.assert_not_called()
        self.agent.cmd_update_sources(self.request, None, IdentityObject(True, 'matrix'))
        self.assertTrue(self.agent.crypto_reply.call_args.kwargs['payload']['ok'])

    def test_challenge_blocks_future_fetches(self):
        with patch('life_signal.life_signal.collector.get', side_effect=Challenge()) as fetch:
            self.agent._collect(self.source)
            self.agent._collect(self.source)
        self.assertEqual(fetch.call_count, 1)
        self.assertIn('example.com', self.agent.engine.snapshot()['blocked_hosts'])

    def test_successful_checks_are_logged_and_unchanged_page_does_not_alert(self):
        with patch('life_signal.life_signal.collector.get', return_value=b'<title>News</title><p>Jane</p>'):
            self.assertTrue(self.agent._collect(self.source))
            self.assertTrue(self.agent._collect(self.source))
        messages = [str(call.args[0]) for call in self.agent.log.call_args_list]
        self.assertTrue(any('baseline established' in msg for msg in messages))
        self.assertTrue(any('check complete' in msg for msg in messages))
        self.assertFalse(self.agent.engine.queue())

    def test_oracle_captcha_verdict_pauses_future_source_queries(self):
        monitored = dict(self.source, analysis_mode='captcha', keywords=[])
        self.agent.engine.replace([monitored], 1)
        oracle = Mock(); oracle.get_universal_id.return_value = 'oracle'
        self.agent.get_nodes_by_role.return_value = [oracle]
        with patch('life_signal.life_signal.collector.get', return_value=b'<title>Page</title><p>Site content</p>') as fetch:
            self.assertTrue(self.agent._collect(monitored))
            query = next(iter(self.agent.engine.queue()))
            self.agent._send_oracle()
            self.agent.cmd_oracle_response({'query_id': query, 'response': '{"captcha":"yes","summary":"Verification form"}'},
                                           None, IdentityObject(True, 'oracle'))
            self.agent._collect(monitored)
        self.assertEqual(fetch.call_count, 1)
        self.assertIn('example.com', self.agent.engine.snapshot()['blocked_hosts'])
        self.assertFalse(self.agent.engine.snapshot()['events'])

    def test_oracle_answer_routes_report_to_service_role_once(self):
        self.agent.engine.record_observation('one', 'old', self.source['url'], 'Story')
        query = self.agent.engine.record_observation('one', 'new', self.source['url'], 'Story')
        oracle = Mock(); oracle.get_universal_id.return_value = 'oracle'
        oracle.get_handler.return_value = 'cmd_msg_prompt'
        relay = Mock(); relay.get_universal_id.return_value = 'telegram'
        relay.get_handler.return_value = 'cmd_send_alert_msg'
        self.agent.get_nodes_by_role.side_effect = lambda role, **kw: [oracle] if role == 'hive.oracle' else [relay]
        self.agent._send_oracle()
        fragment = self.agent.pass_packet.call_args.args[0].get_packet()['content']
        prompt = json.loads(base64.b64decode(fragment['fragment']))
        self.assertEqual(prompt['query_id'], query)
        self.assertIn('new', prompt['messages'][-1]['content'])
        self.agent.cmd_oracle_response({'query_id': query, 'response': '{"match":true,"summary":"A report"}'},
                                       None, IdentityObject(True, 'other'))
        self.assertFalse(self.agent.engine.snapshot()['events'])
        self.agent.cmd_oracle_response({'query_id': query, 'response': '{"match":true,"summary":"A report"}'},
                                       None, IdentityObject(True, 'oracle'))
        self.agent._dispatch(); self.agent._dispatch()
        self.assertEqual(self.agent.pass_packet.call_count, 2)
        notice = self.agent.pass_packet.call_args.args[0].get_packet()
        self.assertIn('A report', notice['content']['msg'])
        self.assertEqual(self.agent.pass_packet.call_args.args[1], 'telegram')

    def test_wikipedia_stream_dispatches_matching_edit(self):
        wiki = dict(self.source, kind='wikipedia', url='https://en.wikipedia.org/wiki/Jane_Example')
        self.agent.engine.replace([wiki], 1)
        self.agent.running = True
        self.agent._collect = Mock()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status_code = 200
        response.headers = {'Content-Type': 'text/event-stream'}
        def lines(**kwargs):
            yield 'id: cursor-1'
            yield 'data: {"wiki":"enwiki","namespace":0,"title":"Jane Example"}'
            self.agent.running = False
        response.iter_lines.side_effect = lines
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.return_value = response
        with patch('life_signal.life_signal.collector.public_host'), \
                patch('life_signal.life_signal.requests.Session', return_value=session):
            self.agent._stream()
        self.assertIn('one', self.agent.engine.snapshot()['wiki_dirty'])
        self.agent._collect.assert_not_called()

    def test_large_feed_item_is_fragmented_into_valid_packets(self):
        self.agent.engine.record_feed('one', [])
        self.agent.engine.record_feed('one', [{'id': 'item', 'url': 'https://example.com/story',
                                                'title': 'Story', 'text': 'A' * 100000}])
        oracle = Mock(); oracle.get_universal_id.return_value = 'oracle'
        self.agent.get_nodes_by_role.return_value = [oracle]
        self.agent._send_oracle()
        packets = [call.args[0].get_packet() for call in self.agent.pass_packet.call_args_list]
        self.assertGreater(len(packets), 1)
        assembly = PromptAssembly()
        result = None
        for packet in packets:
            self.assertTrue(guard_packet_size(packet))
            result = assembly.accept('life-one', packet['content'])
        self.assertIn('A' * 100000, result['messages'][-1]['content'])

    def test_wikipedia_change_is_collected_after_cooldown(self):
        wiki = dict(self.source, kind='wikipedia', url='https://en.wikipedia.org/wiki/Jane_Example')
        self.agent.engine.replace([wiki], 1)
        self.agent.engine.record_observation('one', 'baseline', wiki['url'], 'Jane')
        self.agent.engine.mark_wiki_dirty('one')
        self.agent._stream_started = threading.Lock()
        self.agent._stream_thread = Mock()
        self.agent._beacon = Mock()
        self.agent._collect = Mock(return_value=True)
        self.agent._send_oracle = Mock(); self.agent._dispatch = Mock()
        with patch('life_signal.life_signal.interruptible_sleep'):
            self.agent.worker()
        self.agent._collect.assert_called_once_with(wiki)
        self.assertNotIn('one', self.agent.engine.snapshot()['wiki_dirty'])

    def test_shorter_interval_reschedules_from_last_check(self):
        self.agent.engine.record_observation('one', 'baseline', self.source['url'], 'Story', now=900)
        self.agent._scheduled_sources['one'] = (self.source['url'], 'page', True, 3600)
        self.agent._next_checks['one'] = 4500
        self.agent.engine.replace([dict(self.source, interval_sec=120)], 1)
        self.agent._stream_started = threading.Lock()
        self.agent._stream_thread = Mock(); self.agent._beacon = Mock()
        self.agent._collect = Mock(return_value=True)
        self.agent._send_oracle = Mock(); self.agent._dispatch = Mock()
        with patch('life_signal.life_signal.interruptible_sleep'), patch('life_signal.life_signal.time.time', return_value=1000):
            self.agent.worker()
        self.agent._collect.assert_not_called()
        self.assertEqual(self.agent._next_checks['one'], 1020)
        with patch('life_signal.life_signal.interruptible_sleep'), patch('life_signal.life_signal.time.time', return_value=1020):
            self.agent.worker()
        self.agent._collect.assert_called_once()


if __name__ == '__main__': unittest.main()
