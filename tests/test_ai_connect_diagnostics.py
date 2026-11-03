"""AI Connect failure guidance and launch denial."""
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import time
from PyQt6.QtCore import QObject, QCoreApplication
from matrix_gui.modules.access_control.session_diagnostics import SessionDiagnostics

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'phoenix'))
sys.path.insert(0, str(ROOT / 'phoenix_terminal'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from matrix_gui.modules.access_control.live_gateway import LiveGateway, SUPPORTED
from phoenix_terminal.swarm_inspection import DiagnosticReadError

class ConnectTests(unittest.TestCase):
    def test_connect_failure_reports_uncertainty_and_closes_failed_session(self):
        dispatcher = Mock()
        dispatcher.call.side_effect = [{'sessions': [{'session_id': 'synthetic'}]}, {}]
        remote = Mock()
        remote.bind.side_effect = DiagnosticReadError('Signed reply timed out.')
        stub = SimpleNamespace(dispatcher=dispatcher, remote=remote, evidence_ready=Mock())
        with self.assertRaises(DiagnosticReadError) as caught:
            LiveGateway._connect_session(stub, 'sessions.open', 'deployment', Mock())
        message = str(caught.exception)
        self.assertIn('hive may be down or unreachable', message)
        self.assertIn('cannot determine the cause', message)
        self.assertEqual(dispatcher.call.call_args.args[0], 'diagnostic.stop')

    def test_verified_tree_warns_once_per_active_flip_and_ignores_wrong_sender(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        class Parent(QObject):
            def __init__(self):
                super().__init__(); self.warnings = []
            def matrix_tree_warning(self, *args): self.warnings.append(args)
        class Lease:
            connection_id = 'client'
            def __call__(self): return True
        parent = Parent()
        target = SimpleNamespace(matrix_uid='matrix', deployment={'id': 'deployment'})
        session = SessionDiagnostics(target, 'a' * 32, Lease(), parent)
        node = {'universal_id': 'matrix', 'name': 'matrix', 'children': [{
            'universal_id': 'agent', 'name': 'worker', 'children': [],
            'agent_status': {'checked_at': time.time(), 'spawn': {'count': 4, 'flip_tripping': True}}}]}
        payload = {'verified_sender': 'matrix', 'runtime_id': '20261103_010203', 'timestamp': time.time(), 'content': node}
        session._receive_tree(dict(payload, verified_sender='other'))
        self.assertEqual(parent.warnings, [])
        session._receive_tree(payload)
        self.assertEqual(parent.warnings, [])  # A tree alone is not a verified Connect.
        session.connection_readiness = {'state': 'ready'}
        session._receive_tree(payload); session._receive_tree(payload)
        self.assertEqual(len(parent.warnings), 1)
        self.assertTrue(parent.warnings[0][1][1]['matrix_spawn']['flip_tripping'])
        node['children'][0]['agent_status']['spawn']['flip_tripping'] = False
        session._receive_tree(payload)
        node['children'][0]['agent_status']['spawn']['flip_tripping'] = True
        session._receive_tree(payload)
        self.assertEqual(len(parent.warnings), 2)

    def test_live_warning_requires_agent_inventory_permission(self):
        import threading
        broker = SimpleNamespace(_lock=threading.RLock(), grants={'request': SimpleNamespace(connection_id='client')})
        stub = SimpleNamespace(broker=broker, evidence_ready=Mock())
        session = SimpleNamespace(connection_id='client', target=SimpleNamespace(deployment={'id': 'deployment'}),
                                  runtime_id='20261103_010203', readiness=lambda: {'state': 'ready'}, binding=lambda: {'runtime_id': '20261103_010203'})
        with patch('matrix_gui.modules.access_control.live_gateway._Lease') as cls:
            cls.return_value.return_value = False
            LiveGateway.matrix_tree_warning(stub, session, [], {})
            stub.evidence_ready.emit.assert_not_called()
            cls.return_value.return_value = True
            LiveGateway.matrix_tree_warning(stub, session, [], {})
            stub.evidence_ready.emit.assert_called_once()
            self.assertEqual(cls.call_args.args[2], ('agents.list',))

    def test_ai_mode_does_not_allow_railgun(self):
        self.assertNotIn('railgun.launch', SUPPORTED)
        self.assertIn('sessions.open', SUPPORTED)

if __name__ == '__main__': unittest.main()
