"""Signed lifecycle authorization is published only after a durable tree save."""
import os
import json
import select
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'matrixos'))
from Crypto.PublicKey import RSA
from core.python_core import reap_revision as rev
from core.python_core.lifecycle_fence import LifecycleFence
from core.python_core.mixin.reap_status_handler import ReapStatusHandlerMixin


class Fence:
    def __init__(self, *args): pass
    @contextmanager
    def exclusive(self, **kwargs): yield
    def read_state(self): return {'boot_id': 'boot', 'generation': 'generation'}


class Fixture:
    def __init__(self, root, key):
        self._runtime_comm_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        self.matrix_priv_obj = key
        self.matrix_pub = key.publickey()
        self.command_line_args = {'universe': 'universe'}
        self.path_resolution = {'install_path': root}
        node = {'lifecycle_status': {'transaction_id': 'tx', 'op_stage': 'shutdown_probe', 'op': 'shutdown_restart', 'locked': True}}
        self._agent_tree_master = SimpleNamespace(root={'target': node}, nodes={'target': node})
        self._agent_tree_master.reparse = lambda: setattr(self._agent_tree_master, 'nodes', self._agent_tree_master.root)
        self.meta = {}
    def save_agent_tree_master(self):
        rev.note_reap_save_attempt(self)
        rev.note_reap_save_success(self)
        return True
    def log(self, *args, **kwargs): pass
    def get_agent_tree_master(self): return self._agent_tree_master
    def read(self):
        return rev.read_reap_authorization(self._runtime_comm_fd, public_key=self.matrix_pub,
            universe='universe', boot_id='boot', generation='generation')[0]
    @rev.reap_mutation
    def change(self, stage):
        self._agent_tree_master.nodes['target']['lifecycle_status']['op_stage'] = stage
        self.save_agent_tree_master()
        rev.commit_reap_mutation(self)
    @rev.reap_mutation
    def noop(self): pass
    @rev.reap_mutation
    def deferred_noop(self, callback):
        rev.defer_reap_side_effect(self, callback)
    @rev.reap_mutation
    def update_heartbeat(self):
        self.meta['heartbeat'] = self.meta.get('heartbeat', 0) + 1
        self.save_agent_tree_master()
        rev.commit_reap_mutation(self)


class RevisionGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.key = RSA.generate(2048)
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.obj = Fixture(self.tmp.name, self.key)
        self.addCleanup(os.close, self.obj._runtime_comm_fd)
        self.env = patch.dict(os.environ, {rev.GENERATION_ENV: 'generation'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.fence = patch.object(rev, 'LifecycleFence', Fence)
        self.fence.start(); self.addCleanup(self.fence.stop)
    def test_bootstrap_noop_and_new_revision(self):
        self.obj.noop()
        first = self.obj.read()
        self.obj.noop()
        self.assertEqual(first['revision'], self.obj.read()['revision'])
        dispatched = []
        self.obj.deferred_noop(lambda: dispatched.append(self.obj.read()['revision']))
        self.assertEqual(dispatched, [first['revision']])
        self.obj.update_heartbeat()
        self.assertEqual(first['revision'], self.obj.read()['revision'])
        self.obj.change('restart_start')
        second = self.obj.read()
        self.assertNotEqual(first['revision'], second['revision'])
        self.assertEqual(second['targets']['target']['stage'], 'restart_start')
    def test_idle_watcher_does_not_invalidate_delayed_proof(self):
        self.obj.noop()
        revision = self.obj.read()['revision']
        ReapStatusHandlerMixin._guarded_reaper_transaction_watcher(self.obj)
        self.assertEqual(self.obj.read()['revision'], revision)
    def test_map_replace_then_reported_failure_stays_pending(self):
        self.obj.noop()
        real_write = rev._write_map
        count = 0
        def fail_after_commit(obj, data):
            nonlocal count
            count += 1
            real_write(obj, data)
            if count == 2: raise OSError('simulated fsync failure after replacement')
        with patch.object(rev, '_write_map', side_effect=fail_after_commit):
            with self.assertRaises(OSError): self.obj.change('restart_start')
        with self.assertRaises(rev.ReapTransactionError): self.obj.read()
        self.assertEqual(self.obj._agent_tree_master.nodes['target']['lifecycle_status']['op_stage'], 'shutdown_probe')
        with self.assertRaises(rev.ReapTransactionError): self.obj.noop()

    def test_directory_sync_failure_after_marker_unlink_keeps_committed_state(self):
        self.obj.noop()
        original = os.fsync
        failures = []
        def fail_after_unlink(fd):
            marker = Path(self.tmp.name) / 'directive' / rev._PENDING_FILE
            if os.path.isdir(f'/proc/self/fd/{fd}') and not marker.exists():
                failures.append(True)
                raise OSError('simulated directory fsync failure after unlink')
            return original(fd)
        with patch.object(rev.os, 'fsync', side_effect=fail_after_unlink):
            self.obj.change('restart_start')
        self.assertTrue(failures)
        self.assertEqual(self.obj.read()['targets']['target']['stage'], 'restart_start')
        self.assertEqual(self.obj._agent_tree_master.nodes['target']['lifecycle_status']['op_stage'], 'restart_start')

    def test_reused_boot_reestablishes_authenticated_map_for_new_generation(self):
        self.obj.noop()
        previous = self.obj.read()
        with patch.dict(os.environ, {rev.GENERATION_ENV: 'next-generation'}), \
                patch.object(Fence, 'read_state', return_value={'boot_id': 'boot', 'generation': 'next-generation'}):
            self.obj.noop()
            updated = rev.read_reap_authorization(self.obj._runtime_comm_fd, public_key=self.obj.matrix_pub,
                universe='universe', boot_id='boot', generation='next-generation')[0]
        self.assertNotEqual(previous['revision'], updated['revision'])

    def test_other_process_waits_for_commit_and_observes_new_revision(self):
        base = Path(self.tmp.name)
        directory = base / 'universes' / 'lifecycle' / 'universe'
        directory.mkdir(parents=True)
        for path in (base, base / 'universes', directory.parent, directory):
            path.chmod(0o755)
        lock = directory / 'lock'
        lock.write_text(json.dumps({'version': 1, 'state': 'STOPPED', 'generation': None, 'boot_id': None}))
        lock.chmod(0o660)
        generation, boot = 'a' * 32, '20261111_120000'
        def fence(*args): return LifecycleFence(base, 'universe', _owner_uid=os.getuid())
        with fence().exclusive() as held:
            held.write_state('ACTIVE', generation, boot)
        key_file = base / 'public.pem'
        key_file.write_bytes(self.obj.matrix_pub.export_key())
        self.fence.stop()
        self.fence = patch.object(rev, 'LifecycleFence', side_effect=fence)
        self.fence.start()
        self.addCleanup(self.fence.stop)
        with patch.dict(os.environ, {rev.GENERATION_ENV: generation}):
            self.obj.noop()
            old = rev.read_reap_authorization(self.obj._runtime_comm_fd, public_key=self.obj.matrix_pub,
                universe='universe', boot_id=boot, generation=generation)[0]['revision']
            script = '''import os, sys\nfrom core.python_core.lifecycle_fence import LifecycleFence\nfrom core.python_core.reap_revision import read_reap_authorization\nprint("waiting", flush=True)\nwith LifecycleFence(sys.argv[1], "universe", _owner_uid=os.getuid()).exclusive(expected_generation=sys.argv[2]):\n fd=os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY)\n result=read_reap_authorization(fd, public_key=open(sys.argv[1]+"/public.pem", "rb").read(), universe="universe", boot_id=sys.argv[3], generation=sys.argv[2])\n print(result[0]["revision"], flush=True)\n'''
            process = None
            original = rev._write_map
            calls = 0
            def start_contender(obj, data):
                nonlocal calls, process
                calls += 1
                original(obj, data)
                if calls == 2:
                    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'matrixos')}
                    process = subprocess.Popen([sys.executable, '-B', '-c', script, str(base), generation, boot],
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                    self.assertEqual(process.stdout.readline().strip(), 'waiting')
                    self.assertFalse(select.select([process.stdout], [], [], 0.2)[0])
            with patch.object(rev, '_write_map', side_effect=start_contender):
                self.obj.change('restart_start')
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertNotEqual(stdout.strip(), old)

if __name__ == '__main__': unittest.main()
