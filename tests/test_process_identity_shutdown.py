import os
import signal
import subprocess
import sys
import time
from unittest.mock import patch

import psutil
import unittest
import tempfile
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "matrixos"))

from core.python_core.class_lib.processes.b2_bomber import B2Bomber, PinnedProcess, ProcessIdentityUnavailable
from core.python_core.class_lib.processes.reaper import Reaper, _matches_job


class ProcessShutdownTests(unittest.TestCase):
  def test_mismatched_start_time_does_not_signal_or_claim_exit(self):
      with subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']) as child:
          try:
              started = psutil.Process(child.pid).create_time()
              bomber = B2Bomber()
              bomber.log_info = lambda _: None
              record = {'pid': child.pid, 'universal_id': 'test', 'process_started_at': started + 1}
              with patch('os.killpg', side_effect=AssertionError('process group must not be signaled')):
                  remaining = bomber.escalate_shutdown([record], 0, 0)
              assert remaining
              assert child.poll() is None
              with self.assertRaises(ProcessIdentityUnavailable):
                  PinnedProcess(child.pid, started + 1)
          finally:
              child.terminate()
              child.wait(timeout=5)


  def test_missing_identity_refuses_to_signal(self):
      with subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']) as child:
          try:
              bomber = B2Bomber()
              bomber.log_info = lambda _: None
              remaining = bomber.escalate_shutdown([{'pid': child.pid, 'universal_id': 'old'}], 0, 0)
              assert remaining
              assert child.poll() is None
          finally:
              child.terminate()
              child.wait(timeout=5)


  def test_pinned_process_is_signaled_individually(self):
      with subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']) as child:
          ref = PinnedProcess(child.pid, psutil.Process(child.pid).create_time())
          try:
              bomber = B2Bomber()
              bomber.log_info = lambda _: None
              with patch('os.killpg', side_effect=AssertionError('process group must not be signaled')):
                  remaining = bomber.escalate_shutdown([{'pid': child.pid, 'universal_id': 'test', 'process_ref': ref}], .2, 2)
              child.wait(timeout=5)
              assert not remaining
          finally:
              ref.close()
              if child.poll() is None:
                  child.kill()
                  child.wait()


  def test_changed_command_fails_closed(self):
      proc = psutil.Process()
      with self.assertRaises(ProcessIdentityUnavailable):
          PinnedProcess(os.getpid(), proc.create_time(), expected_cmd=['different'])



  def test_unverified_records_do_not_receive_die_cookie(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pod = root / 'pod'
        pod.mkdir()
        (pod / 'boot.json').write_text(json.dumps({'pid': os.getpid(), 'universal_id': 'agent', 'cmd': psutil.Process().cmdline()}))
        reaper = Reaper(root, root / 'comm', timeout_sec=0)
        reaper.log_info = lambda _: None
        (root / 'comm').mkdir()
        reaper._pod_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        reaper._comm_fd = os.open(root / 'comm', os.O_RDONLY | os.O_DIRECTORY)
        try:
            reaper._pass_out_die_cookies_locked([pod])
        finally:
            os.close(reaper._pod_fd)
            os.close(reaper._comm_fd)
        self.assertFalse((root / 'comm' / 'agent' / 'incoming' / 'die').exists())
        self.assertTrue(reaper.is_cmdline_still_alive(next(iter(reaper.agents.values()))))

  def test_missing_or_broken_boot_record_remains_unresolved(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        missing = root / 'missing'
        missing.mkdir()
        broken = root / 'broken'
        broken.mkdir()
        (broken / 'boot.json').write_text('{')
        reaper = Reaper(root, root / 'comm', timeout_sec=0)
        reaper.log_info = lambda _: None
        (root / 'comm').mkdir()
        reaper._pod_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        reaper._comm_fd = os.open(root / 'comm', os.O_RDONLY | os.O_DIRECTORY)
        try:
            reaper._pass_out_die_cookies_locked([missing, broken])
        finally:
            os.close(reaper._pod_fd)
            os.close(reaper._comm_fd)
        self.assertEqual(len(reaper.agents), 2)
        self.assertTrue(all(reaper.is_cmdline_still_alive(record) for record in reaper.agents.values()))

  def test_job_labels(self):
    for command, expected in [
        (['python', '--job', 'alpha:agent'], True),
        (['python', '--job=alpha:agent'], True),
        (['python', '--job', 'alphabet:agent'], False),
        (['python', '--job', 'alpha:agent:other'], False),
        (['python', 'alpha:agent'], False),
    ]:
        self.assertEqual(_matches_job(command, 'alpha'), expected)

if __name__ == '__main__':
    unittest.main()
