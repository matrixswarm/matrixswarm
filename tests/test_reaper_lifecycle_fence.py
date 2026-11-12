"""Targeted shutdown must not race a boot or an old generation."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
from core.python_core.lifecycle_fence import LifecycleError, LifecycleFence
from core.python_core.class_lib.processes.reaper import Reaper
from core.python_core.class_lib.processes.reaper_universal_id_handler import ReaperUniversalHandler


class ReaperFenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.universe = "example"
        self.generation = "a" * 32
        self.boot = "20261111_123456"
        directory = self.base / "universes" / "lifecycle" / self.universe
        directory.mkdir(parents=True, mode=0o700)
        directory.parent.parent.chmod(0o700)
        directory.parent.chmod(0o700)
        directory.chmod(0o700)
        (directory / "lock").touch(mode=0o660)
        (directory / "lock").chmod(0o660)
        self.fence = LifecycleFence(self.base, self.universe, _owner_uid=os.getuid())
        with self.fence.exclusive():
            self.fence.write_state("ACTIVE", self.generation, self.boot)
        runtime = self.base / "universes" / "runtime" / self.universe / self.boot
        self.pods = runtime / "pod"
        self.comm = runtime / "comm"
        self.pods.mkdir(parents=True)
        self.comm.mkdir()
        self.factory = patch("core.python_core.class_lib.processes.reaper.LifecycleFence",
                             side_effect=lambda base, uid: LifecycleFence(base, uid, _owner_uid=os.getuid()))
        self.factory.start()
        self.addCleanup(self.factory.stop)
        self.kwargs = dict(lifecycle_base=self.base, lifecycle_universe=self.universe,
                           lifecycle_generation=self.generation)

    def test_handler_holds_exclusive_lock_through_target_processing(self):
        pod = self.pods / "pod1"
        pod.mkdir()
        (pod / "boot.json").write_text(json.dumps({"universal_id": "target"}))
        entered, release = threading.Event(), threading.Event()

        def wait(_self):
            entered.set()
            self.assertTrue(release.wait(3))
            return True

        handler = ReaperUniversalHandler(self.pods, self.comm, **self.kwargs)
        result = []
        with patch.object(Reaper, "_pass_out_die_cookies_locked"), patch.object(Reaper, "wait_for_agents_shutdown", wait):
            thread = threading.Thread(target=lambda: result.append(handler.process_all_universal_ids(["target"], wait_seconds=0)))
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                with self.assertRaises(LifecycleError):
                    with self.fence.shared(self.generation):
                        self.fail("A spawn entered while targeted shutdown held the fence")
            finally:
                release.set()
                thread.join(3)
        self.assertEqual(result, [True])

    def test_stale_generation_and_wrong_boot_cannot_modify_channels(self):
        stale = dict(self.kwargs, lifecycle_generation="b" * 32)
        reaper = Reaper(self.pods, self.comm, **stale)
        with self.assertRaises(LifecycleError):
            reaper.drop_die_tokens_from_tree({"universal_id": "target"})
        wrong = Reaper(self.pods.parent.parent / "other" / "pod", self.comm, **self.kwargs)
        with self.assertRaises(LifecycleError):
            wrong.drop_die_tokens_from_tree({"universal_id": "target"})
        self.assertFalse((self.comm / "target").exists())

    def test_missing_context_and_other_universe_fail_closed(self):
        unconfigured = Reaper(self.pods, self.comm)
        for action in (lambda: unconfigured.pass_out_die_cookies([]),
                       unconfigured.escalate_shutdown, unconfigured.reap_all,
                       lambda: unconfigured.drop_die_tokens_from_tree({}),
                       lambda: unconfigured.kill_universe_processes("example", passes=0)):
            with self.assertRaises(LifecycleError):
                action()
        reaper = Reaper(self.pods, self.comm, **self.kwargs)
        with self.assertRaises(LifecycleError):
            reaper.kill_universe_processes("other:target", passes=0)

    def test_invalid_tree_id_fails_before_any_die_token(self):
        reaper = Reaper(self.pods, self.comm, **self.kwargs)
        with self.assertRaises(ValueError):
            reaper.drop_die_tokens_from_tree({"universal_id": "valid", "children": [
                {"universal_id": "../outside"}]})
        self.assertFalse((self.comm / "valid").exists())

    def test_foreign_pod_and_job_records_are_not_trusted(self):
        reaper = Reaper(self.pods, self.comm, **self.kwargs)
        foreign = self.base / "outside"
        foreign.mkdir()
        (foreign / "boot.json").write_text(json.dumps({"universal_id": "target", "pid": os.getpid()}))
        pod = self.pods / "pod1"
        pod.mkdir()
        (pod / "boot.json").write_text(json.dumps({"universal_id": "target", "pid": os.getpid(),
                                                   "cmd": ["python", "--job", "other:target"]}))
        reaper.pass_out_die_cookies([foreign, pod])
        self.assertEqual(len(reaper.agents), 2)
        self.assertTrue(all(record.get("identity_unverified") for record in reaper.agents.values()))
        self.assertFalse((self.comm / "target").exists())

    def test_ancestor_replacement_does_not_redirect_die_token(self):
        reaper = Reaper(self.pods, self.comm, **self.kwargs)
        old_boot = self.pods.parent
        moved = old_boot.parent / "original-boot"
        outside = self.base / "outside"
        (outside / "comm" / "target" / "incoming").mkdir(parents=True)
        with reaper.lifecycle_guard():
            old_boot.rename(moved)
            old_boot.symlink_to(outside, target_is_directory=True)
            reaper._drop_die_tokens_from_tree_locked({"universal_id": "target"})
        self.assertEqual((moved / "comm/target/incoming/die").read_text(), "terminate")
        self.assertFalse((outside / "comm/target/incoming/die").exists())

    def test_symlinked_boot_record_is_unverifiable(self):
        pod = self.pods / "pod1"
        pod.mkdir()
        outside = self.base / "outside.json"
        outside.write_text(json.dumps({"universal_id": "target"}))
        (pod / "boot.json").symlink_to(outside)
        handler = ReaperUniversalHandler(self.pods, self.comm, **self.kwargs)
        self.assertFalse(handler.process_all_universal_ids(["target"], wait_seconds=0))
        self.assertFalse((self.comm / "target").exists())
        self.assertEqual(json.loads(outside.read_text()), {"universal_id": "target"})

    def test_symlinked_incoming_does_not_redirect_token(self):
        pod = self.pods / "pod1"
        pod.mkdir()
        (pod / "boot.json").write_text(json.dumps({"universal_id": "target", "pid": os.getpid(),
                                                   "process_started_at": 1,
                                                   "cmd": ["python", "--job", "example:target"]}))
        outside = self.base / "outside"
        outside.mkdir()
        target = self.comm / "target"
        target.mkdir()
        (target / "incoming").symlink_to(outside, target_is_directory=True)
        reaper = Reaper(self.pods, self.comm, **self.kwargs)
        pinned = Mock()
        with patch("core.python_core.class_lib.processes.reaper.PinnedProcess", return_value=pinned):
            reaper.pass_out_die_cookies([pod])
        self.assertFalse((outside / "die").exists())
        self.assertTrue(all(record.get("identity_unverified") for record in reaper.agents.values()))
        pinned.close.assert_called_once()

    def test_valid_boot_record_writes_anchored_tokens(self):
        pod = self.pods / "pod1"
        pod.mkdir()
        (pod / "boot.json").write_text(json.dumps({"universal_id": "target", "pid": os.getpid(),
                                                   "process_started_at": 1,
                                                   "cmd": ["python", "--job", "example:target"]}))
        reaper = Reaper(self.pods, self.comm, **self.kwargs)
        pinned = Mock()
        with patch("core.python_core.class_lib.processes.reaper.PinnedProcess", return_value=pinned):
            reaper.pass_out_die_cookies([pod])
        self.assertEqual(json.loads((self.comm / "target/incoming/die").read_text()), "terminate")
        self.assertEqual(json.loads((self.comm / "target/incoming/tombstone").read_text()), "true")
        self.assertEqual((pod / "tombstone").read_text(), "true")
        pinned.close()

    def test_existing_tombstone_is_never_overwritten(self):
        directory = self.comm / "target"
        directory.mkdir()
        marker = directory / "tombstone"
        marker.write_text("existing")
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            Reaper._write_tombstone_if_missing(fd)
        finally:
            os.close(fd)
        self.assertEqual(marker.read_text(), "existing")


if __name__ == "__main__":
    unittest.main()
