"""Detached vault transforms serialize, persist, and complete on the Qt thread."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))
from PyQt6.QtCore import QEventLoop, QThread, QTimer
from PyQt6.QtWidgets import QApplication
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton, VaultSavedReopenRequired


class VaultAsyncTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.core = VaultCoreSingleton({"padding": "x" * 300, "deployments": {"dep": {"value": "old"}},
                                        "workspaces": {}}, "pw", Path(self.temp.name) / "vault.json")

    def test_runs_off_gui_blocks_conflicts_and_publishes_after_success(self):
        gate = threading.Event()
        entered = threading.Event()
        writes = []
        callbacks = []
        loop = QEventLoop()
        gui_thread = QThread.currentThread()

        def transform(section):
            entered.set()
            if not gate.wait(3):
                raise TimeoutError("worker stalled")
            section["dep"]["value"] = "new"
            return section, "digest"

        def save(snapshot, password, path):
            writes.append((deepcopy(snapshot), QThread.currentThread() == gui_thread))

        def complete(result, error):
            callbacks.append((result, error, QThread.currentThread() == gui_thread))
            loop.quit()

        with patch("matrix_gui.modules.vault.services.vault_service_loader.save_vault_singlefile", side_effect=save):
            self.core.transform_section_async("deployments", transform, complete)
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.core.read()["deployments"]["dep"]["value"], "old")
            self.assertFalse(self.core.patch("registry", {"new": {}}))
            with self.assertRaisesRegex(RuntimeError, "busy"):
                self.core.transform_section_async("deployments", transform, complete)
            QTimer.singleShot(30, gate.set)
            QTimer.singleShot(3000, loop.quit)
            loop.exec()
        self.assertEqual(callbacks, [("digest", None, True)])
        self.assertEqual(writes[0][0]["deployments"]["dep"]["value"], "new")
        self.assertFalse(writes[0][1])
        self.assertEqual(self.core.read()["deployments"]["dep"]["value"], "new")
        self.assertIsNone(self.core._workspace_active)

    def test_failed_transform_and_failed_save_leave_live_data_unchanged(self):
        for failure in ("transform", "save"):
            with self.subTest(failure=failure):
                before = self.core.read()
                done = []
                loop = QEventLoop()
                def transform(section):
                    if failure == "transform":
                        raise ValueError("stale")
                    section["dep"]["value"] = "new"
                    return section, "digest"
                def save(*args):
                    if failure == "save":
                        raise OSError("read-only")
                with patch("matrix_gui.modules.vault.services.vault_service_loader.save_vault_singlefile", side_effect=save):
                    self.core.transform_section_async("deployments", transform,
                        lambda result, error: (done.append((result, error)), loop.quit()))
                    QTimer.singleShot(3000, loop.quit)
                    loop.exec()
                self.assertEqual(len(done), 1)
                self.assertIsNone(done[0][0])
                self.assertIsInstance(done[0][1], ValueError if failure == "transform" else OSError)
                self.assertEqual(self.core.read(), before)
                self.assertIsNone(self.core._workspace_active)

    def test_copy_failure_occurs_before_disk_write(self):
        before = self.core.read()
        done = []
        loop = QEventLoop()
        with patch("matrix_gui.modules.vault.services.vault_transform_writer.deepcopy", side_effect=MemoryError("copy")), \
             patch("matrix_gui.modules.vault.services.vault_service_loader.save_vault_singlefile") as save:
            self.core.transform_section_async("deployments", lambda section: (section, "digest"),
                lambda result, error: (done.append((result, error)), loop.quit()))
            QTimer.singleShot(3000, loop.quit)
            loop.exec()
        save.assert_not_called()
        self.assertEqual(self.core.read(), before)
        self.assertIsInstance(done[0][1], MemoryError)

    def test_in_memory_publication_failure_reports_saved_and_blocks_future_writes(self):
        class FailingDict(dict):
            def clear(self):
                raise MemoryError("cannot publish")
        self.core.data["deployments"] = FailingDict(self.core.data["deployments"])
        done = []
        loop = QEventLoop()
        def transform(section):
            section["dep"]["value"] = "new"
            return section, "digest"
        with patch("matrix_gui.modules.vault.services.vault_service_loader.save_vault_singlefile") as save:
            self.core.transform_section_async("deployments", transform,
                lambda result, error: (done.append((result, error)), loop.quit()))
            QTimer.singleShot(3000, loop.quit)
            loop.exec()
        save.assert_called_once()
        self.assertEqual(len(done), 1)
        self.assertIsInstance(done[0][1], VaultSavedReopenRequired)
        self.assertIn("vault was saved", str(done[0][1]))
        self.assertTrue(self.core._closed)
        self.assertFalse(self.core.patch("registry", {}))

    def test_workspace_queued_during_transform_uses_published_snapshot(self):
        gate = threading.Event()
        entered = threading.Event()
        writes = []
        done = []
        loop = QEventLoop()
        def transform(section):
            entered.set()
            if not gate.wait(3):
                raise TimeoutError("worker stalled")
            section["dep"]["value"] = "new"
            return section, "digest"
        def save(snapshot, password, path):
            writes.append(deepcopy(snapshot))
        with patch("matrix_gui.modules.vault.services.vault_service_loader.save_vault_singlefile", side_effect=save):
            self.core.transform_section_async("deployments", transform, lambda result, error: done.append("transform"))
            self.assertTrue(entered.wait(2))
            self.core.save_workspace_async({"uuid": "workspace", "name": "saved"},
                                           lambda ok: (done.append(("workspace", ok)), loop.quit()))
            QTimer.singleShot(30, gate.set)
            QTimer.singleShot(3000, loop.quit)
            loop.exec()
        self.assertEqual(done, ["transform", ("workspace", True)])
        self.assertEqual(len(writes), 2)
        self.assertEqual(writes[1]["deployments"]["dep"]["value"], "new")
        self.assertEqual(writes[1]["workspaces"]["workspace"]["name"], "saved")

    def test_registry_edit_during_transform_is_refused_without_live_mutation(self):
        registry = self.core.get_store("registry")
        deployments = self.core.get_store("deployments")
        self.core.data["registry"]["ssh"] = {"existing": {"host": "old"}}
        old_registry_buffer = registry._buffer
        old_deployment_buffer = deployments._buffer
        gate, entered = threading.Event(), threading.Event()
        done = []
        loop = QEventLoop()
        def transform(section):
            entered.set()
            if not gate.wait(3):
                raise TimeoutError("worker stalled")
            section["dep"]["value"] = "new"
            return section, "digest"
        with patch("matrix_gui.modules.vault.services.vault_service_loader.save_vault_singlefile"):
            self.core.transform_section_async("deployments", transform,
                lambda result, error: (done.append((result, error)), loop.quit()))
            self.assertTrue(entered.wait(2))
            detached = registry.get_namespace("ssh")
            detached["other"] = {"host": "not saved"}
            self.assertNotIn("other", self.core.data["registry"]["ssh"])
            self.assertFalse(registry.set_namespace("ssh", detached))
            self.assertFalse(deployments.commit_candidate({"changed": {}}))
            with self.assertRaisesRegex(RuntimeError, "busy"):
                registry.set_value("other", {})
            with self.assertRaisesRegex(RuntimeError, "busy"):
                registry.delete("ssh")
            self.assertIs(registry._buffer, old_registry_buffer)
            QTimer.singleShot(30, gate.set)
            QTimer.singleShot(3000, loop.quit)
            loop.exec()
        self.assertEqual(done, [("digest", None)])
        self.assertIs(deployments._buffer, old_deployment_buffer)
        self.assertEqual(deployments.get_dep("dep")["value"], "new")
        self.assertEqual(self.core.data["registry"]["ssh"], {"existing": {"host": "old"}})
        registry.set_value("later", {"ok": True})
        self.assertIn("later", self.core.data["registry"])


if __name__ == "__main__":
    unittest.main()
