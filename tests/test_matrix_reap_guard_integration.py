"""Exercise real Matrix handlers through signed lifecycle publication."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from Crypto.PublicKey import RSA

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'matrixos'))
from core.python_core import reap_revision as revision
from core.python_core.tree_parser import TreeParser
from test_reap_revision_guard import Fence

spec = importlib.util.spec_from_file_location('matrix_reap_integration', ROOT / 'matrixos/agents/python_core/matrix/matrix.py')
module = importlib.util.module_from_spec(spec)
with patch.dict(os.environ, {'SITE_ROOT': str(ROOT / 'matrixos'), 'AGENT_PATH': str(ROOT / 'matrixos/agents/python_core')}):
    spec.loader.exec_module(module)


class MatrixGuardIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = RSA.generate(2048)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.fd = os.open(temp.name, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {revision.GENERATION_ENV: 'generation'}).start()
        patch.object(revision, 'LifecycleFence', Fence).start()
        self.agent = module.Agent.__new__(module.Agent)
        a = self.agent
        a._runtime_comm_fd = self.fd
        a.path_resolution = {'install_path': temp.name, 'comm_path': temp.name}
        a.command_line_args = {'universe': 'universe', 'universal_id': 'matrix'}
        a.matrix_priv_obj = self.key
        a.matrix_pub = self.key.publickey()
        a.meta = {}
        a.tree_node = {}
        a.tree_path_dict = {}
        a.log = Mock()
        a.crypto_reply = Mock()
        a.delegate_tree_to_agent = Mock()
        a.get_matrix_universal_id = Mock(return_value='matrix')
        a._agent_tree_master = TreeParser({'universal_id': 'matrix', 'children': [
            {'universal_id': 'target', 'name': 'worker', 'children': []}]})
        a._agent_tree_master.reparse()
        def save(*args, **kwargs):
            revision.note_reap_save_attempt(a)
            revision.note_reap_save_success(a)
            return True
        a.save_agent_tree_master = save

    def read_map(self):
        return revision.read_reap_authorization(self.fd, public_key=self.agent.matrix_pub,
            universe='universe', boot_id='boot', generation='generation')[0]

    def test_restart_commits_real_handler_and_locked_noop_preserves_revision(self):
        self.assertTrue(self.agent._cmd_restart_subtree({'target_universal_id': 'target'}, {}))
        state = self.read_map()
        self.assertEqual(state['targets']['target']['stage'], 'shutdown_probe')
        self.assertFalse(self.agent._cmd_restart_subtree({'target_universal_id': 'target'}, {}))
        self.assertEqual(self.read_map()['revision'], state['revision'])

    def test_completion_replies_only_after_authorization_commit(self):
        self.assertTrue(self.agent._cmd_restart_subtree({'target_universal_id': 'target'}, {}))
        tree = self.agent._agent_tree_master
        node = tree.get_node('target')
        node['lifecycle_status']['agent_status_callback'] = {'session_id': 's'}
        # Publish this test setup through the same guarded handler contract.
        @revision.reap_mutation
        def publish_setup(agent):
            agent.save_agent_tree_master()
            agent.commit_reap_mutation()
        publish_setup(self.agent)
        observed = []
        self.agent.crypto_reply.side_effect = lambda **kw: observed.append(self.read_map()['targets']['target']['locked'])
        self.agent._restart_complete_callback([('target', node)])
        self.assertEqual(observed, [False])
        self.assertFalse(self.read_map()['targets']['target']['locked'])

    def test_failed_restart_save_pauses_authorization_and_restores_tree(self):
        @revision.reap_mutation
        def bootstrap(agent):
            pass
        bootstrap(self.agent)
        def fail(*args, **kwargs):
            revision.note_reap_save_attempt(self.agent)
            return False
        self.agent.save_agent_tree_master = fail
        with self.assertRaises(revision.ReapTransactionError):
            self.agent._cmd_restart_subtree({'target_universal_id': 'target'}, {})
        self.assertNotIn('lifecycle_status', self.agent._agent_tree_master.get_node('target'))
        with self.assertRaises(revision.ReapTransactionError):
            self.read_map()
        self.agent.crypto_reply.assert_not_called()

    def test_completed_restart_is_not_watched_again(self):
        self.assertTrue(self.agent._cmd_restart_subtree({'target_universal_id': 'target'}, {}))
        node = self.agent._agent_tree_master.get_node('target')
        @revision.reap_mutation
        def publish_setup(agent):
            node['lifecycle_status'].update(op_stage='restart_cleanup',
                reported_stage='restart_cleanup', success=True, reap_result={'state': 'cleaned'})
            agent.save_agent_tree_master()
            agent.commit_reap_mutation()
        publish_setup(self.agent)
        self.agent._guarded_reaper_transaction_watcher(force=True)
        self.assertEqual(node['lifecycle_status']['op_stage'], '_complete_callback')
        revision_before = self.read_map()['revision']
        self.agent.log.reset_mock()
        self.agent._guarded_reaper_transaction_watcher(force=True)
        self.assertEqual(self.read_map()['revision'], revision_before)
        self.assertFalse(any('waiting on' in str(call) or 'not successful' in str(call)
                             for call in self.agent.log.call_args_list))


if __name__ == '__main__':
    unittest.main()
