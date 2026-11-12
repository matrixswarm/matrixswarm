"""Linux platform selection and a real spawned Qt window embedding probe."""
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))
from matrix_gui.core.utils.qt_platform import configure_qt_platform


def child_session(conn):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from matrix_gui.core.utils.session_embedding import prepare_embedded_session_window, bind_embedded_session_window
    app = QApplication([])
    win = QMainWindow()
    conn.send(("ready", prepare_embedded_session_window(win)))
    def poll():
        if conn.poll():
            cmd = conn.recv()
            if cmd[0] == "bind":
                bind_embedded_session_window(win, cmd[1], 800, 600)
                conn.send(("bound", win.isVisible()))
            elif cmd[0] == "stop":
                app.exit(0)
    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(10)
    app.exec()
    conn.close()


def probe():
    from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
    from matrix_gui.core.utils.session_embedding import create_embedded_session_container
    app = QApplication([])
    assert app.platformName() == "xcb"
    host = QWidget()
    layout = QVBoxLayout(host)
    host.show()
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=child_session, args=(child,))
    process.start()
    child.close()
    try:
        assert parent.poll(15), "child did not create window"
        kind, wid = parent.recv()
        assert kind == "ready"
        container = create_embedded_session_container(wid)
        layout.addWidget(container)
        app.processEvents()
        parent.send(("bind", int(container.winId())))
        assert parent.poll(15), "child event loop did not bind window"
        assert parent.recv() == ("bound", True)
        host.close()
        host.deleteLater()
        app.processEvents()
        parent.send(("stop",))
        deadline = time.monotonic() + 5
        while process.is_alive() and time.monotonic() < deadline:
            app.processEvents()
            process.join(0.01)
        assert process.exitcode == 0, f"child exit: {process.exitcode}"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        parent.close()
        host.close()


class LinuxSessionEmbeddingTests(unittest.TestCase):
    def test_platform_selection_preserves_explicit_choices(self):
        cases = [
            ({"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}, "xcb"),
            ({"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0", "QT_QPA_PLATFORM": "offscreen"}, "offscreen"),
            ({"XDG_SESSION_TYPE": "wayland"}, None),
            ({"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}, None),
        ]
        for env, expected in cases:
            with self.subTest(env=env):
                configure_qt_platform(environ=env, platform="linux")
                self.assertEqual(env.get("QT_QPA_PLATFORM"), expected)
        env = {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}
        configure_qt_platform(environ=env, platform="win32")
        self.assertNotIn("QT_QPA_PLATFORM", env)

    @unittest.skipUnless(sys.platform.startswith("linux") and os.environ.get("DISPLAY"), "requires X11 or XWayland")
    def test_spawned_qt_session_embeds_on_xcb(self):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "xcb"
        result = subprocess.run([sys.executable, __file__, "--probe"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("event loop is already running", result.stderr)


if __name__ == "__main__":
    if "--probe" in sys.argv:
        probe()
    else:
        unittest.main()
