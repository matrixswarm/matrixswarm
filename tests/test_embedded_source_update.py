"""Synthetic vault checks for editing an encrypted embedded directive."""
import base64
from copy import deepcopy
import hashlib
import multiprocessing
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from matrix_gui.modules.vault.crypto.deploy_tools import (
    decrypt_swarm_encrypted_directive, generate_swarm_encrypted_directive,
)
from matrix_gui.modules.vault.crypto.vault_handler import load_vault_singlefile, save_vault_singlefile
from matrix_gui.modules.vault.embedded_source_update import (
    EmbeddedSourceUpdateError, bundle_fingerprint, update_embedded_source, embedded_source_transform,
)
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.modules.vault.services.vault_connection_singleton import SerializedConnection, VaultConnectionSingleton
from matrix_gui.core.panel.hotswap_agent_panel import EmbeddedSourceWorker
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication


class EmbeddedSourceUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "vault.json"
        self.tree = {"universal_id": "matrix", "children": [
            {"universal_id": "agent-a", "src_embed": base64.b64encode(b"old source").decode(), "children": []},
            {"universal_id": "agent-b", "src_embed": base64.b64encode(b"other source").decode(), "children": []},
        ]}
        bundle, key, _ = generate_swarm_encrypted_directive(deepcopy(self.tree), clown_car=False, hashbang=False)
        self.key = base64.b64encode(key).decode()
        self.record = {"label": "synthetic", "agents": [], "encrypted_bundle": bundle,
                       "encrypted_hash": bundle_fingerprint(bundle), "swarm_key": self.key}
        self.data = {"padding": "x" * 256, "deployments": {"dep": self.record}}
        self.core = VaultCoreSingleton(deepcopy(self.data), "synthetic-password", self.path)
        save_vault_singlefile(self.data, "synthetic-password", str(self.path))
        self.source = b"print('new source')\n"
        self.encoded = base64.b64encode(self.source).decode()
        self.digest = hashlib.sha256(self.source).hexdigest()
        self.fingerprint = bundle_fingerprint(bundle)

    def save_event(self, event, **kwargs):
        if event == "vault.update":
            save_vault_singlefile(kwargs["data"], kwargs["password"], kwargs["vault_path"])
            kwargs["receipt"]["saved"] = True

    def update(self, *, fingerprint=None, target="agent-a", digest=None):
        return update_embedded_source(self.core, "dep", fingerprint or self.fingerprint,
                                      target, self.encoded, digest or self.digest)

    def test_updates_only_selected_embedded_source_and_keeps_live_key(self):
        with patch("matrix_gui.modules.vault.services.vault_core_singleton.EventBus.emit", side_effect=self.save_event):
            self.assertEqual(self.update(), self.digest)
        saved = load_vault_singlefile("synthetic-password", str(self.path))["deployments"]["dep"]
        self.assertEqual(saved["swarm_key"], self.key)
        self.assertEqual(saved["encrypted_hash"], bundle_fingerprint(saved["encrypted_bundle"]))
        updated = decrypt_swarm_encrypted_directive(saved["encrypted_bundle"], saved["swarm_key"])
        self.assertEqual(updated["children"][0]["src_embed"], self.encoded)
        self.assertEqual(updated["children"][0]["hash_bang"], self.digest)
        self.assertEqual(updated["children"][1], self.tree["children"][1])

    def test_failed_save_leaves_memory_and_vault_unchanged(self):
        original = self.path.read_bytes()
        before = self.core.read()
        with patch("matrix_gui.modules.vault.services.vault_core_singleton.EventBus.emit"):
            with self.assertRaisesRegex(EmbeddedSourceUpdateError, "SAVE_FAILED"):
                self.update()
        self.assertEqual(self.core.read(), before)
        self.assertEqual(self.path.read_bytes(), original)

    def test_stale_deployment_and_bad_source_are_rejected(self):
        original = self.core.read()
        with patch("matrix_gui.modules.vault.services.vault_core_singleton.EventBus.emit") as emit:
            with self.assertRaisesRegex(EmbeddedSourceUpdateError, "DEPLOYMENT_CHANGED"):
                self.update(fingerprint="0" * 64)
            with self.assertRaisesRegex(EmbeddedSourceUpdateError, "SOURCE_MISMATCH"):
                self.update(digest="0" * 64)
            with self.assertRaisesRegex(EmbeddedSourceUpdateError, "AGENT_NOT_UNIQUE"):
                self.update(target="missing")
            emit.assert_not_called()
        self.assertEqual(self.core.read(), original)

    def test_duplicate_agent_id_refuses_update_without_writing(self):
        tree = deepcopy(self.tree)
        tree["children"].append(deepcopy(tree["children"][0]))
        bundle, key, _ = generate_swarm_encrypted_directive(tree, clown_car=False, hashbang=False)
        self.core.data["deployments"]["dep"].update(
            encrypted_bundle=bundle, swarm_key=base64.b64encode(key).decode())
        before = self.core.read()
        with patch("matrix_gui.modules.vault.services.vault_core_singleton.EventBus.emit") as emit:
            with self.assertRaisesRegex(EmbeddedSourceUpdateError, "AGENT_NOT_UNIQUE"):
                self.update(fingerprint=bundle_fingerprint(bundle))
            emit.assert_not_called()
        self.assertEqual(self.core.read(), before)

    def test_source_is_not_rejected_by_the_local_python_parser(self):
        # Phoenix and the target may run different Python versions; the vault
        # editor stores the selected bytes without asserting target syntax.
        source = b"not valid in this interpreter (:"
        with patch("matrix_gui.modules.vault.services.vault_core_singleton.EventBus.emit", side_effect=self.save_event):
            update_embedded_source(self.core, "dep", self.fingerprint, "agent-a",
                base64.b64encode(source).decode(), hashlib.sha256(source).hexdigest())
        record = load_vault_singlefile("synthetic-password", str(self.path))["deployments"]["dep"]
        updated = decrypt_swarm_encrypted_directive(record["encrypted_bundle"], record["swarm_key"])
        self.assertEqual(base64.b64decode(updated["children"][0]["src_embed"]), source)

    def test_wrapped_directive_and_urlsafe_key_remain_compatible(self):
        tree = {"agent_tree": deepcopy(self.tree), "meta": {"kept": True}}
        bundle, key, _ = generate_swarm_encrypted_directive(tree, clown_car=False, hashbang=False)
        urlsafe_key = base64.urlsafe_b64encode(key).decode()
        self.core.data["deployments"]["dep"].update(
            encrypted_bundle=bundle, encrypted_hash=bundle_fingerprint(bundle), swarm_key=urlsafe_key)
        with patch("matrix_gui.modules.vault.services.vault_core_singleton.EventBus.emit", side_effect=self.save_event):
            update_embedded_source(self.core, "dep", bundle_fingerprint(bundle), "agent-a",
                                   self.encoded, self.digest)
        record = self.core.read()["deployments"]["dep"]
        self.assertEqual(record["swarm_key"], urlsafe_key)
        updated = decrypt_swarm_encrypted_directive(record["encrypted_bundle"], urlsafe_key)
        self.assertEqual(updated["meta"], {"kept": True})
        self.assertEqual(updated["agent_tree"]["children"][0]["hash_bang"], self.digest)

    def test_background_save_through_session_pipe_keeps_event_loop_running(self):
        parent, child = multiprocessing.Pipe()
        self.addCleanup(parent.close)
        self.addCleanup(child.close)
        source = b"# " + b"x" * 100000 + b"\nprint('ready')\n"
        encoded = base64.b64encode(source).decode()
        digest = hashlib.sha256(source).hexdigest()
        gate = threading.Event()
        failures = []

        def cockpit():
            try:
                request = parent.recv()
                if not gate.wait(3):
                    raise RuntimeError("GUI event loop stalled")
                result = update_embedded_source(self.core, request["dep_id"], request["expected_bundle_hash"],
                                                request["agent_id"], request["source"], request["sha256"])
                parent.send({"type": "vault.embedded_source.response", "dep_id": "dep",
                             "request_id": request["request_id"], "ok": True, "sha256": result})
            except Exception as error:
                failures.append(error)

        vault = VaultConnectionSingleton("dep", SerializedConnection(child))
        worker = EmbeddedSourceWorker(vault, "agent-a", encoded, digest, self.fingerprint)
        outcome = []
        loop = QEventLoop()
        worker.result.connect(lambda ok, message: (outcome.append((ok, message)), loop.quit()))
        thread = threading.Thread(target=cockpit)
        with patch("matrix_gui.modules.vault.services.vault_core_singleton.EventBus.emit", side_effect=self.save_event):
            thread.start()
            worker.start()
            QTimer.singleShot(50, gate.set)
            QTimer.singleShot(5000, loop.quit)
            loop.exec()
            thread.join(timeout=3)
            worker.wait(3000)
        self.assertFalse(thread.is_alive())
        self.assertFalse(worker.isRunning())
        self.assertFalse(failures, failures)
        self.assertTrue(outcome and outcome[0][0], outcome)
        record = load_vault_singlefile("synthetic-password", str(self.path))["deployments"]["dep"]
        updated = decrypt_swarm_encrypted_directive(record["encrypted_bundle"], record["swarm_key"])
        self.assertEqual(updated["children"][0]["src_embed"], encoded)
        self.assertEqual(record["swarm_key"], self.key)

    def test_real_cockpit_writer_stays_responsive_during_slow_save(self):
        parent, child = multiprocessing.Pipe()
        self.addCleanup(parent.close)
        self.addCleanup(child.close)
        vault = VaultConnectionSingleton("dep", SerializedConnection(child))
        worker = EmbeddedSourceWorker(vault, "agent-a", self.encoded, self.digest, self.fingerprint)
        loop = QEventLoop()
        outcome, ticks = [], []
        entered = threading.Event()
        release = threading.Event()

        def slow_save(data, password, path):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("GUI event loop stalled during vault save")
            save_vault_singlefile(data, password, path)

        def handle_request():
            if not parent.poll():
                return
            request = parent.recv()
            transform = embedded_source_transform(request["dep_id"], request["expected_bundle_hash"],
                                                  request["agent_id"], request["source"], request["sha256"])
            def completed(result, error):
                parent.send({"type": "vault.embedded_source.response", "dep_id": "dep",
                             "request_id": request["request_id"], "ok": error is None, "sha256": result})
            self.core.transform_section_async("deployments", lambda section: (transform(section), self.digest), completed)
            request_timer.stop()

        def tick():
            if entered.is_set():
                ticks.append(True)
                release.set()

        request_timer = QTimer()
        request_timer.timeout.connect(handle_request)
        request_timer.start(5)
        tick_timer = QTimer()
        tick_timer.timeout.connect(tick)
        tick_timer.start(10)
        worker.result.connect(lambda ok, message: (outcome.append((ok, message)), loop.quit()))
        with patch("matrix_gui.modules.vault.services.vault_service_loader.save_vault_singlefile", side_effect=slow_save):
            worker.start()
            QTimer.singleShot(5000, loop.quit)
            loop.exec()
            release.set()
            worker.wait(3000)
        request_timer.stop(); tick_timer.stop()
        self.assertFalse(worker.isRunning())
        self.assertTrue(ticks, "The Qt event loop did not run while the writer was blocked")
        self.assertTrue(outcome and outcome[0][0], outcome)
        record = load_vault_singlefile("synthetic-password", str(self.path))["deployments"]["dep"]
        self.assertEqual(decrypt_swarm_encrypted_directive(record["encrypted_bundle"], self.key)
                         ["children"][0]["src_embed"], self.encoded)


if __name__ == "__main__":
    unittest.main()
