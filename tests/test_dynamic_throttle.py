"""Check worker pacing and shutdown without creating real CPU pressure."""
import ast
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
import types
import unittest
from contextlib import contextmanager


SOURCE = Path(__file__).resolve().parents[1] / "matrixos/core/python_core/boot_agent.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
agent = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BootAgent")
methods = [node for node in agent.body if isinstance(node, ast.FunctionDef) and node.name in {"start_dynamic_throttle", "_throttled_worker_wrapper", "_throttled_worker_anchored"}]
namespace = {"os": os, "queue": queue, "time": time}
exec(compile(ast.Module(body=methods, type_ignores=[]), str(SOURCE), "exec"), namespace)


class Probe:
    start_dynamic_throttle = namespace["start_dynamic_throttle"]
    _throttled_worker_wrapper = namespace["_throttled_worker_wrapper"]
    _throttled_worker_anchored = namespace["_throttled_worker_anchored"]

    def __init__(self, root, load=0):
        self.path_resolution = {"comm_path_resolved": root, "comm_path": root}
        self.command_line_args = {"universal_id": "test"}
        self.FootballType = types.SimpleNamespace(CATCH="catch")
        self.running = True
        self.throttle_queue = queue.Queue(1)
        self.load = load
        self.debug = types.SimpleNamespace(is_enabled=lambda: False)

    def get_load(self):
        return self.load

    def log(self, *args, **kwargs):
        pass

    @contextmanager
    def _own_comm_zone(self, name, *, create=False):
        fd = os.open(os.path.join(self.path_resolution["comm_path_resolved"], "clock"), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            yield fd
        finally:
            os.close(fd)

    def get_football(self, **kwargs):
        return object()

    def get_reception_agent(self, *args, **kwargs):
        class Receiver:
            def set_location(self, *args): return self
            def set_address(self, *args): return self
            def set_drop_zone(self, *args): return self
            def set_directory_fd(self, *args): return self
            def close(self): pass
        return Receiver()


class ImmediateThread:
    def __init__(self, target, daemon):
        self.target = target

    def start(self):
        self.target()


class DynamicThrottleTests(unittest.TestCase):
    def test_load_scales_delay_and_caps_it(self):
        namespace["threading"] = types.SimpleNamespace(Thread=ImmediateThread)
        delays = []
        def sleep(agent, delay):
            delays.append(delay)
            agent.running = False
        namespace["interruptible_sleep"] = sleep
        with tempfile.TemporaryDirectory() as root:
            for load, expected in ((0, 2), (2, 2), (2.5, 4), (3, 6), (4, 10), (8, 10)):
                with self.subTest(load=load):
                    probe = Probe(root, load)
                    probe.start_dynamic_throttle()
                    self.assertEqual(delays[-1], expected)
                    self.assertTrue(probe.throttle_queue.get_nowait())

    def test_waiting_worker_exits_after_shutdown(self):
        namespace["interruptible_sleep"] = lambda agent, delay: None
        with tempfile.TemporaryDirectory() as root:
            probe = Probe(root)
            worker = threading.Thread(target=probe._throttled_worker_wrapper, daemon=True)
            worker.start()
            time.sleep(0.1)
            probe.running = False
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive(), "worker remained blocked on throttle queue")
