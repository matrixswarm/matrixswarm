"""Oracle must preserve complete prompts or reject them explicitly."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'matrixos'))
sys.path.insert(0, str(ROOT / 'matrixos' / 'agents' / 'python_core'))
os.environ.setdefault('SITE_ROOT', str(ROOT / 'matrixos'))
os.environ.setdefault('AGENT_PATH', str(ROOT / 'matrixos' / 'agents' / 'python_core'))
from oracle.oracle import Agent, input_limit
from oracle.prompt_assembly import PromptAssembly
from core.python_core.class_lib.packet_delivery.utility.security.packet_size import guard_packet_size
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
import base64


class OracleInputTests(unittest.TestCase):
    def make_agent(self):
        agent = object.__new__(Agent)
        agent.encryption_enabled = False
        agent.response_mode = 'terse'
        agent.max_input_chars = 200000
        agent.command_line_args = {'universal_id': 'oracle'}
        agent.tree_node = {'config': {}}
        agent._cfg_lock = threading.Lock()
        agent.client = Mock()
        agent.client.chat.completions.create.return_value.choices = [Mock(message=Mock(content='{"match":false}'))]
        agent.model = 'gpt-4o'; agent.temperature = 0
        agent.progress = Mock(); agent.progress.attempt.return_value = nullcontext()
        agent.log = Mock(); agent.dump_messages_check = Mock()
        agent.get_delivery_packet = Mock(return_value=Mock())
        agent.pass_packet = Mock()
        return agent

    def test_long_prompt_keeps_every_message(self):
        agent = self.make_agent()
        messages = [{'role': 'system', 'content': 'instructions'}] + [
            {'role': 'user', 'content': str(i) * 3000} for i in range(7)]
        agent._cmd_msg_prompt_worker({'messages': messages, 'target_universal_id': 'caller',
            'query_id': 'q', 'return_handler': 'answer'}, None, None)
        sent = agent.client.chat.completions.create.call_args.kwargs['messages']
        self.assertEqual(sent, messages)

    def test_oversized_prompt_returns_explicit_error_without_call(self):
        agent = self.make_agent(); agent.max_input_chars = 1000
        agent._cmd_msg_prompt_worker({'messages': [{'role': 'user', 'content': 'x' * 2000}],
            'target_universal_id': 'caller', 'query_id': 'q', 'return_handler': 'answer',
            'json_response': True}, None, None)
        agent.client.chat.completions.create.assert_not_called()
        packet = agent.get_delivery_packet.return_value
        payload = packet.set_data.call_args.args[0]['content']
        self.assertEqual(json.loads(payload['response'])['error'], 'input_too_large')
        agent.pass_packet.assert_called_once()

    def test_invalid_limit_uses_default(self):
        self.assertEqual(input_limit(None), 200000)
        self.assertEqual(input_limit(9999999), 1000000)

    def test_fragmented_large_prompt_respects_packet_bounds_and_reassembles(self):
        request = {'query_id': 'query', 'target_universal_id': 'life',
                   'return_handler': 'reply', 'messages': [{'role': 'user', 'content': '🐝' * 40000}]}
        raw = json.dumps(request, ensure_ascii=False).encode('utf-8')
        chunks = [raw[i:i+8000] for i in range(0, len(raw), 8000)]
        assembly = PromptAssembly()
        packets = [{'query_id': 'query', 'index': i, 'count': len(chunks),
                    'fragment': base64.b64encode(chunk).decode('ascii')} for i, chunk in enumerate(chunks)]
        for packet in reversed(packets[1:]):
            self.assertTrue(guard_packet_size({'handler': 'cmd_prompt_fragment', 'content': packet}))
            self.assertIsNone(assembly.accept('life', packet))
        self.assertEqual(assembly.accept('life', packets[0]), request)
        self.assertIsNone(assembly.accept('life', packets[0]))

    def test_fragment_assembly_is_sender_scoped_and_checks_identity(self):
        request = {'query_id': 'q', 'target_universal_id': 'life', 'messages': []}
        data = base64.b64encode(json.dumps(request).encode()).decode()
        packet = {'query_id': 'q', 'index': 0, 'count': 1, 'fragment': data}
        with self.assertRaises(ValueError): PromptAssembly().accept('other', packet)

    def test_fragment_handler_only_accepts_verified_sender(self):
        agent = self.make_agent()
        agent._prompt_assembly = PromptAssembly()
        agent._spawn_service_thread = Mock()
        request = {'query_id': 'q', 'target_universal_id': 'life', 'messages': []}
        packet = {'query_id': 'q', 'index': 0, 'count': 1,
                  'fragment': base64.b64encode(json.dumps(request).encode()).decode()}
        agent.cmd_prompt_fragment(packet, None, IdentityObject(False, 'life'))
        agent._spawn_service_thread.assert_not_called()
        agent.cmd_prompt_fragment(packet, None, IdentityObject(True, 'life'))
        self.assertEqual(agent._spawn_service_thread.call_args.args[1], request)


if __name__ == '__main__': unittest.main()
