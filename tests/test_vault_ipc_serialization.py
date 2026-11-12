"""Exercise GUI polling and worker requests sharing the same session pipe."""
import multiprocessing
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from matrix_gui.core.session_window import SessionWindow
from matrix_gui.modules.vault.services.vault_connection_singleton import (
    SerializedConnection, VaultConnectionSingleton,
)


class VaultIPCSerializationTests(unittest.TestCase):
    def test_gui_timer_does_not_consume_worker_response(self):
        parent, child = multiprocessing.Pipe()
        self.addCleanup(parent.close)
        self.addCleanup(child.close)
        conn = SerializedConnection(child)
        vault = VaultConnectionSingleton("dep", conn)
        fake_window = SimpleNamespace(conn=conn, vault_singleton=vault,
                                      _pipe_timer=SimpleNamespace(stop=Mock()))
        outcome = []

        def worker():
            try:
                outcome.append(vault.update_embedded_source("agent", "YQ==", "a" * 64, "b" * 64))
            except Exception as error:
                outcome.append(error)

        thread = threading.Thread(target=worker)
        thread.start()
        self.addCleanup(lambda: thread.join(timeout=3))
        self.assertTrue(parent.poll(3))
        request = parent.recv()
        start = time.monotonic()
        SessionWindow._poll_conn(fake_window)
        self.assertLess(time.monotonic() - start, 0.5)
        parent.send({"type": "unrelated"})
        parent.send({"type": "vault.embedded_source.response", "dep_id": "dep",
                     "request_id": request["request_id"], "ok": True, "sha256": "a" * 64})
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome, [True])
        self.assertEqual(vault.take_deferred_messages(), [{"type": "unrelated"}])

    def test_pipe_writes_from_two_threads_are_serialized(self):
        class OverlapDetector:
            def __init__(self):
                self.active = 0
                self.overlap = False

            def send(self, value):
                self.active += 1
                self.overlap |= self.active > 1
                time.sleep(0.02)
                self.active -= 1

        raw = OverlapDetector()
        conn = SerializedConnection(raw)
        first = threading.Thread(target=conn.send, args=("one",))
        second = threading.Thread(target=conn.send, args=("two",))
        first.start(); second.start()
        first.join(); second.join()
        self.assertFalse(raw.overlap)

    def test_late_registry_response_cannot_satisfy_deployment_query(self):
        parent, child = multiprocessing.Pipe()
        self.addCleanup(parent.close)
        self.addCleanup(child.close)
        vault = VaultConnectionSingleton("dep", SerializedConnection(child))
        vault.load({"label": "cached deployment"})
        self.assertEqual(vault.fetch_fresh("registry", timeout=0.05), {})
        old_request = parent.recv()
        result = []
        thread = threading.Thread(target=lambda: result.append(vault.fetch_fresh("deployment", timeout=3)))
        thread.start()
        self.addCleanup(lambda: thread.join(timeout=3))
        self.assertTrue(parent.poll(3))
        new_request = parent.recv()
        parent.send({"type": "vault.response", "dep_id": "dep", "target": "registry",
                     "request_id": old_request["request_id"], "data": {"ssh": "stale"}})
        parent.send({"type": "vault.response", "dep_id": "dep", "target": "deployment",
                     "request_id": new_request["request_id"], "data": {"label": "fresh"}})
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [{"label": "fresh"}])
        self.assertEqual(vault.read_deployment(), {"label": "fresh"})


if __name__ == "__main__":
    unittest.main()
