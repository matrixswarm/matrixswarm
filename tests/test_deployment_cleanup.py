import os
import sys
from pathlib import Path
from copy import deepcopy
import unittest
import threading
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from PyQt6.QtWidgets import QApplication
from matrix_gui.modules.railgun.deployment_cleanup import prepare_cleanup
from matrix_gui.modules.directive.deploy_options_dialog import DeployOptionsDialog
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.swarm_workspace.cls_lib.deployment.dialog.railgun import RailgunDialog, RailgunWorker


class CleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.vault = Mock()
        def record(host="192.0.2.1", universe="test", port=22):
            return {"universe": universe, "railgun_target_identity": {"host": host, "port": port}}
        self.vault.data = {"deployments": {"new": record(), "old": record(),
            "other-ip": record("192.0.2.2"), "other-universe": record(universe="other"),
            "other-port": record(port=2222), "legacy": {"universe": "test"}}}
        self.vault.patch.side_effect = lambda key, value: self.vault.data.update({key: value}) or True
        self.vault._lock = threading.RLock()
        self.vault._closed = False
        self.vault._workspace_active = None
        self.vault._workspace_queue = []
        self.vault.transform_section.side_effect = lambda key, fn: VaultCoreSingleton.transform_section(self.vault, key, fn)
        self.active = patch("matrix_gui.modules.vault.services.vault_core_singleton.VaultCoreSingleton.get", return_value=self.vault)
        self.active.start()
        self.addCleanup(self.active.stop)

    def test_matching_only_and_idempotent(self):
        finish = prepare_cleanup(self.vault, "new", True)
        self.assertEqual(finish(), 1)
        self.assertEqual(finish(), 0)
        self.assertEqual(set(self.vault.data["deployments"]), {"new", "other-ip", "other-universe", "other-port", "legacy"})

    def test_disabled_changed_and_later_records_are_preserved(self):
        self.assertEqual(prepare_cleanup(self.vault, "new", False)(), 0)
        finish = prepare_cleanup(self.vault, "new", True)
        self.vault.data["deployments"]["old"]["label"] = "edited"
        self.vault.data["deployments"]["later"] = deepcopy(self.vault.data["deployments"]["new"])
        self.assertEqual(finish(), 0)

    def test_failed_write_preserves_live_records(self):
        before = deepcopy(self.vault.data)
        finish = prepare_cleanup(self.vault, "new", True)
        self.vault.patch.side_effect = None
        self.vault.patch.return_value = False
        with self.assertRaises(RuntimeError):
            finish()
        self.assertEqual(self.vault.data, before)

    def test_replaced_current_record_blocks_cleanup(self):
        finish = prepare_cleanup(self.vault, "new", True)
        self.vault.data["deployments"]["new"]["label"] = "changed"
        with self.assertRaises(RuntimeError):
            finish()
        self.vault.patch.assert_not_called()

    def test_busy_vault_retains_records_and_allows_later_retry(self):
        finish = prepare_cleanup(self.vault, "new", True)
        self.vault._workspace_active = object()
        with self.assertRaises(RuntimeError):
            finish()
        self.assertIn("old", self.vault.data["deployments"])
        self.vault._workspace_active = None
        self.assertEqual(finish(), 1)

    def test_transform_and_patch_share_one_lock(self):
        attempted = []
        def probe():
            acquired = self.vault._lock.acquire(blocking=False)
            attempted.append(acquired)
            if acquired:
                self.vault._lock.release()
        def check():
            thread = threading.Thread(target=probe)
            thread.start()
            thread.join(1)
            self.assertFalse(thread.is_alive())
        def transform(records):
            check()
            records["added"] = {}
            return records
        def patch_section(key, records):
            check()
            self.vault.data[key] = records
            return True
        self.vault.patch.side_effect = patch_section
        self.assertTrue(self.vault.transform_section("deployments", transform))
        self.assertEqual(attempted, [False, False])

    def test_default_checkbox_checked_and_can_opt_out(self):
        dialog = DeployOptionsDialog({}, "test")
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.remove_previous.isChecked())
        dialog.remove_previous.setChecked(False)
        self.assertFalse(dialog.remove_previous.isChecked())

    def test_finish_requires_fresh_receipt_success_and_no_cancel(self):
        for code, fresh, cancelled in ((0, True, False), (1, True, False), (0, False, False), (0, True, True)):
            with self.subTest(code=code, fresh=fresh, cancelled=cancelled):
                cleanup = Mock(return_value=1)
                with patch.object(RailgunWorker, "start"):
                    dialog = RailgunDialog(None, {}, {}, "synthetic", {"success_cleanup": cleanup})
                self.addCleanup(dialog.deleteLater)
                dialog.worker.fresh_success = fresh
                if cancelled:
                    dialog.worker.cancel()
                dialog.finish(code)
                dialog.finish(code)
                self.assertEqual(cleanup.call_count, int(code == 0 and fresh and not cancelled))

    def test_receipt_requires_exact_request_and_supports_split_chunks(self):
        worker = RailgunWorker({}, {}, "synthetic", {"railgun_request_id": "a" * 32})
        worker._stdout(b"[RAILGUN][REPLAY] Request already completed (exit=0)\n")
        self.assertFalse(worker.fresh_success)
        marker = ("[RAILGUN][COMPLETED] request=" + "a" * 32 + " exit=0\n").encode()
        worker._stdout(marker[:25])
        worker._stdout(marker[25:])
        self.assertTrue(worker.fresh_success)


if __name__ == "__main__":
    unittest.main()
