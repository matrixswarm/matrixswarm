"""Matrix's authenticated flip-trip status survives bounded AI inspection."""
import sys
from pathlib import Path
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'matrixos'))
from core.python_core.live_diagnostics import tree_snapshot
from phoenix_terminal.swarm_inspection import session_evidence_context
from phoenix_terminal.compact_inspection import compact_inspection
from test_compact_inspection import report, NOW, OBSERVED

class MatrixFlipTests(unittest.TestCase):
    def test_matrix_status_projection_and_compact_warning(self):
        tree = {'universal_id': 'matrix', 'name': 'matrix', 'children': [
            {'universal_id': 'agent-000', 'name': 'worker', 'children': [],
             'agent_status': {'checked_at': NOW, 'spawn': {'count': 4, 'flip_tripping': True},
                              'private': 'must not leave matrix'}}]}
        snapshot = tree_snapshot(tree, '20261007_000000')
        self.assertEqual(snapshot['nodes'][1]['matrix_spawn']['count'], 4)
        self.assertNotIn('private', str(snapshot))
        binding = {'session_id': 'a' * 32, 'runtime_id': '20261007_000000', 'generation': 0, 'transport': 'phoenix_session'}
        coverage = {'state': 'available', 'observed_at': OBSERVED, 'source': 'matrix_snapshot', 'truncated': False}
        source = report(1, failures=0)
        source.update(session_binding=binding, agent_tree=snapshot['nodes'], agent_tree_coverage=coverage)
        result = compact_inspection('fixture-deployment', source)
        self.assertEqual(result['matrix_flip_warnings'][0]['agent_id'], 'agent-000')
        self.assertTrue(result['matrix_flip_warnings'][0]['fresh'])
        self.assertEqual(result['matrix_status_missing'], 1)
        self.assertIn('Matrix flip-trip warnings', result['reporting_guidance'])
        source['agent_tree'][1]['matrix_spawn']['checked_at'] = NOW - 121
        self.assertFalse(compact_inspection('fixture-deployment', source)['matrix_flip_warnings'][0]['fresh'])

    def test_bad_matrix_status_is_omitted_or_rejected(self):
        tree = {'universal_id': 'matrix', 'name': 'matrix', 'children': [],
                'agent_status': {'checked_at': NOW, 'spawn': {'count': '3', 'flip_tripping': True}}}
        node = tree_snapshot(tree, '20261007_000000')['nodes'][0]
        self.assertNotIn('matrix_spawn', node)
        node['matrix_spawn'] = {'count': 3, 'flip_tripping': 'true', 'checked_at': NOW}
        with self.assertRaises(ValueError):
            session_evidence_context({'session_binding': {'session_id': 'a'*32, 'runtime_id': '20261007_000000', 'generation': 0, 'transport': 'phoenix_session'},
                'agent_tree': [node], 'agent_tree_coverage': {'state': 'available', 'observed_at': OBSERVED, 'source': 'matrix_snapshot', 'truncated': False}}, {})

if __name__ == '__main__': unittest.main()
