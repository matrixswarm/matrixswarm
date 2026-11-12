"""A late background file signal must not abort Phoenix after teardown."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import os, sys, threading, time
sys.path.insert(0, sys.argv[1])
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication, QWidget
from matrix_gui.core.panel.custom_panels.drop_vault.drop_vault import DropVault, FileJob
app = QApplication([])
class Bus:
    def on(self, *args): pass
    def off(self, *args): pass
    def emit(self, *args, **kwargs): pass
started, release = threading.Event(), threading.Event()
def delayed(job):
    started.set()
    if not release.wait(5): return
    if sys.argv[2] == "error":
        job.failed.emit("synthetic read failure")
    else:
        job.completed.emit({"data": b"fixture", "filename": "fixture", "sha256": "fixture"})
    job.finished.emit()
FileJob.run = delayed
parent = QWidget()
panel = DropVault("test", Bus(), node={"universal_id": "fixture"}, session_window=parent)
panel._signals_connected = True
panel._local_job("read", "unused")
assert started.wait(2)
sip.delete(parent)
assert sip.isdeleted(panel)
release.set()
deadline = time.monotonic() + 1
while time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.01)
print("survived")
'''

REOPEN_PROBE = r'''
import sys
sys.path.insert(0, sys.argv[1])
from PyQt6.QtWidgets import QApplication
from matrix_gui.core.panel.custom_panels.drop_vault.drop_vault import DropVault
app = QApplication([])
class Bus:
    def on(self, *args): pass
    def off(self, *args): pass
    def emit(self, *args, **kwargs): pass
DropVault._refresh = lambda self, *args, **kwargs: None
panel = DropVault("test", Bus(), node={"universal_id": "fixture"})
panel.show()
app.processEvents()
assert panel.timer.isActive()
panel.close()
app.processEvents()
assert not panel.timer.isActive()
panel.show()
app.processEvents()
assert panel.timer.isActive()
assert panel._connected and panel._signals_connected
panel.close()
print("reopened")
'''

OTHER_PANELS_PROBE = r'''
import sys
sys.path.insert(0, sys.argv[1])
from PyQt6.QtWidgets import QApplication
from matrix_gui.core.panel.custom_panels.log_watcher.log_watcher import LogWatcher
from matrix_gui.core.panel.custom_panels.wordpress_plugin_guard.plugin_guard import PluginGuard
app = QApplication([])
class Bus:
    def __init__(self): self.items = set()
    def on(self, name, callback): self.items.add((name, callback))
    def off(self, name, callback): self.items.discard((name, callback))
    def emit(self, *args, **kwargs): pass
for cls, timer_name in ((LogWatcher, "_flush_timer"), (PluginGuard, "_update_timer")):
    bus = Bus()
    panel = cls("test", bus, node={"universal_id": "fixture"})
    panel.show(); app.processEvents()
    assert getattr(panel, timer_name).isActive() and len(bus.items) == 1
    panel.hide(); app.processEvents()
    assert not getattr(panel, timer_name).isActive() and len(bus.items) == 0
    panel.show(); app.processEvents()
    assert getattr(panel, timer_name).isActive() and len(bus.items) == 1
    panel.close(); app.processEvents()
    panel.show(); app.processEvents()
    assert getattr(panel, timer_name).isActive() and len(bus.items) == 1
    panel.close(); app.processEvents()
print("timers and subscriptions restored")
'''


class PanelLifecycleTests(unittest.TestCase):
    def test_cached_log_and_wordpress_panels_restart_timers_and_subscriptions(self):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-B", "-c", OTHER_PANELS_PROBE, str(ROOT / "phoenix")],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("timers and subscriptions restored", result.stdout)

    def test_cached_panel_can_reopen_after_close(self):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-B", "-c", REOPEN_PROBE, str(ROOT / "phoenix")],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reopened", result.stdout)

    def test_late_file_signals_after_parent_destruction(self):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        for mode in ("error", "completed"):
            with self.subTest(mode=mode):
                result = subprocess.run(
                    [sys.executable, "-B", "-c", PROBE, str(ROOT / "phoenix"), mode],
                    env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("survived", result.stdout)
