"""Synthetic encrypted evidence and diagnostic failure boundaries; no live access."""
import base64
import json
import unittest
from unittest.mock import Mock, patch

from Crypto.Cipher import AES

from phoenix_terminal.connection_approval import ApprovalResource
from phoenix_terminal.connection_broker import TerminalConnectionBroker, TerminalSnapshot
from phoenix_terminal.remote_access import FixedTarget, RemoteOperations, _exchange
from phoenix_terminal.swarm_inspection import DiagnosticReadError, inspection_page, public_diagnostic_page


class InspectionTests(unittest.TestCase):
    def target(self, connector=None):
        return FixedTarget('fixture', 'test', 'synthetic', 'a' * 64, '{}',
                           connector=connector, log_key=b'x' * 32)

    def test_encrypted_application_error_survives_recent_heartbeat_and_projection(self):
        target = self.target()
        record = {'timestamp': '2026-10-07 00:00:00', 'level': 'INFO',
                  'message': '[ERROR] upstream request failed: insufficient_quota password=SYNTHETIC-SECRET'}
        cipher = AES.new(target.log_key, AES.MODE_GCM, nonce=b'n' * 12)
        ciphertext, tag = cipher.encrypt_and_digest(json.dumps(record).encode())
        line = base64.b64encode(cipher.nonce + tag + ciphertext)
        document = {'version': 1, 'universe': 'test', 'observed_at': '2026-10-07T00:00:01+00:00',
                    'truncated': False, 'logs_truncated': False,
                    'agents': [{'agent_id': 'worker-1', 'process_count': 1,
                                'boot_id': '20261007_000000', 'heartbeat': 'recent'}]}
        document['logs'] = [{'version': 1, 'universe': 'test', 'observed_at': document['observed_at'],
                             'agent_id': 'worker-1', 'boot_id': '20261007_000000',
                             'state': 'readable', 'tail': base64.b64encode(line).decode(),
                             'truncated': False}]
        report = inspection_page('fixture', target, [{'universal_id': 'worker-1', 'name': 'worker'}], document)
        report = public_diagnostic_page('swarm.inspect', 'fixture', report)
        self.assertEqual('attention_required', report['assessment'])
        self.assertEqual('UPSTREAM_QUOTA_EXHAUSTED', report['agents'][0]['findings'][0]['code'])
        self.assertEqual(record['timestamp'], report['agents'][0]['findings'][0]['timestamp'])
        self.assertFalse(report['application_health_verified'])
        self.assertNotIn('SYNTHETIC-SECRET', json.dumps(report))
        self.assertIn('original message withheld', report['agents'][0]['findings'][0]['evidence'])

    def test_closed_ssh_channel_drains_large_stdout_and_stderr_before_receipt(self):
        class ClosedChannel:
            closed = True

            def __init__(self):
                self.output = bytearray(b'o' * 240000)
                self.errors = bytearray(b'e' * 40000)

            def settimeout(self, timeout): pass
            def exec_command(self, command): pass
            def close(self): pass
            def recv_ready(self): return bool(self.output)
            def recv_stderr_ready(self): return bool(self.errors)
            def exit_status_ready(self): return True
            def recv_exit_status(self): return 0

            def recv(self, count):
                chunk = bytes(self.output[:count])
                del self.output[:count]
                return chunk

            def recv_stderr(self, count):
                chunk = bytes(self.errors[:count])
                del self.errors[:count]
                return chunk

        client = Mock()
        client.get_transport.return_value.open_session.return_value = ClosedChannel()
        lease = Mock()
        code, output, errors = _exchange(client, 'synthetic-read-only', lease)
        self.assertEqual(0, code)
        self.assertEqual(b'o' * 240000, output)
        self.assertEqual(b'e' * 40000, errors)
        self.assertGreater(lease.call_count, 2)

    def test_remote_failure_uses_fixed_guidance_without_stderr(self):
        client = Mock()
        remote = RemoteOperations({'fixture': self.target(lambda *a, **k: (client, None))})
        with patch('phoenix_terminal.remote_access._exchange', return_value=(2, b'', b'password=SECRET')):
            with self.assertRaises(DiagnosticReadError) as caught:
                remote.inspect('fixture', lambda: True)
        self.assertIn('update MatrixOS', str(caught.exception))
        self.assertNotIn('SECRET', str(caught.exception))
        client.close.assert_called_once()

    def test_local_processing_failure_identifies_stage_without_exception_text(self):
        client = Mock()
        remote = RemoteOperations({'fixture': self.target(lambda *a, **k: (client, None))})
        with patch('phoenix_terminal.remote_access._exchange', return_value=(0, b'{}', b'')), \
             patch('phoenix_terminal.swarm_inspection.inspection_page', side_effect=ImportError('SECRET')):
            with self.assertRaisesRegex(DiagnosticReadError, 'local evidence processing: missing dependency') as caught:
                remote.inspect('fixture', lambda: True)
        self.assertNotIn('SECRET', str(caught.exception))

    def test_broker_preserves_safe_diagnostic_error_as_value_error_for_http(self):
        resource = ApprovalResource('fixture', 'Synthetic', ('agents.list', 'logs.read'))
        snapshot = TerminalSnapshot('Synthetic', 'a' * 64, (resource,), 60)
        handler = Mock(side_effect=DiagnosticReadError('Fixed diagnostic guidance'))
        broker = TerminalConnectionBroker(snapshot, operation_handlers={
            'swarm.inspect': handler, 'agents.list': Mock(), 'logs.read': Mock()})
        self.addCleanup(broker.close)
        identity = {'request_id': 'fixture', 'client_secret': 's' * 40}
        broker.handle('connection.request', {**identity, 'client_label': 'Synthetic'})
        broker.resolve('fixture', True, 'Synthetic operator approval')
        with self.assertRaisesRegex(ValueError, 'Fixed diagnostic guidance'):
            broker.handle('swarm.inspect', {**identity, 'deployment_id': 'fixture'})


if __name__ == '__main__':
    unittest.main()
