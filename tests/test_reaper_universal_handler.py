"""The targeted reaper must not claim success with unidentifiable pods."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
from core.python_core.class_lib.processes.reaper_universal_id_handler import ReaperUniversalHandler
from core.python_core.class_lib.processes.reaper import Reaper


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pods = self.root / "pods"
        self.pods.mkdir()
        self.pod_fd = os.open(self.pods, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.pod_fd)
        self.reader = Reaper(self.pods, self.root / "comm")
        self.reader._pod_fd = self.pod_fd
        self.handler = ReaperUniversalHandler(self.pods, self.root / "comm")

    def test_missing_corrupt_and_invalid_boot_fail_closed_while_matching_agent_processed(self):
        for contents in (None, "{", "[]", "{}"):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory(dir=self.pods) as bad_dir:
                bad = Path(bad_dir)
                if contents is not None:
                    (bad / "boot.json").write_text(contents)
                good = self.pods / "valid"
                good.mkdir(exist_ok=True)
                (good / "boot.json").write_text(json.dumps({"universal_id": "target"}))
                with patch("core.python_core.class_lib.processes.reaper_universal_id_handler.Reaper") as cls:
                    reaper = cls.return_value
                    reaper._pod_fd = self.pod_fd
                    reaper._read_boot_record.side_effect = self.reader._read_boot_record
                    reaper.agents = {}
                    reaper.wait_for_agents_shutdown.return_value = True
                    self.assertFalse(self.handler.process_all_universal_ids(["target"], wait_seconds=0))
                    reaper._pass_out_die_cookies_locked.assert_called_once_with([good])

    def test_success_and_survivor_status_are_returned_and_refs_closed(self):
        pod = self.pods / "valid"
        pod.mkdir()
        (pod / "boot.json").write_text(json.dumps({"universal_id": "target"}))
        for remaining in ([], [{"pid": 1}]):
            with self.subTest(remaining=remaining), patch("core.python_core.class_lib.processes.reaper_universal_id_handler.Reaper") as cls:
                reaper = cls.return_value
                reaper._pod_fd = self.pod_fd
                reaper._read_boot_record.side_effect = self.reader._read_boot_record
                ref = unittest.mock.Mock()
                reaper.agents = {"target": {"process_ref": ref}}
                reaper.wait_for_agents_shutdown.return_value = False
                reaper._escalate_shutdown_locked.return_value = remaining
                self.assertEqual(self.handler.process_all_universal_ids(["target"], wait_seconds=0), not bool(remaining))
                ref.close.assert_called_once()
