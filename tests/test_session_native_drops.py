"""Windows OLE registration across the actual two-process session boundary."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _session_child(conn):
    import ctypes
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from matrix_gui.core.utils.session_embedding import prepare_embedded_session_window

    app = QApplication([])
    legacy = QMainWindow()
    legacy.setWindowFlags(Qt.WindowType.SubWindow | Qt.WindowType.FramelessWindowHint)
    legacy.create()
    fixed = QMainWindow()
    fixed_id = prepare_embedded_session_window(fixed)
    handles = [int(legacy.winId()), fixed_id]
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetPropW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    user32.GetPropW.restype = ctypes.c_void_p
    user32.GetParent.argtypes = [ctypes.c_void_p]
    user32.GetParent.restype = ctypes.c_void_p
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]

    def snapshot():
        rows = []
        for hwnd in handles:
            parent = user32.GetParent(hwnd)
            parent_pid = ctypes.c_ulong()
            if parent:
                user32.GetWindowThreadProcessId(parent, ctypes.byref(parent_pid))
            rows.append({"registered": bool(user32.GetPropW(hwnd, "OleDropTargetInterface")),
                         "parent_pid": parent_pid.value})
        return rows

    conn.send({"handles": handles, "before": snapshot()})
    try:
        while True:
            app.processEvents()
            if not conn.poll(0.01):
                continue
            command = conn.recv()
            if command == "probe":
                conn.send(snapshot())
            elif command == "quit":
                break
    finally:
        legacy.close()
        fixed.close()
        conn.close()


def _native_probe():
    import multiprocessing
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QWindow
    from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

    sys.path.insert(0, str(ROOT / "phoenix"))
    app = QApplication([])
    host = QWidget()
    host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    layout = QVBoxLayout(host)
    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe()
    child = ctx.Process(target=_session_child, args=(child_conn,))
    child.start()
    child_conn.close()
    try:
        if not parent_conn.poll(15):
            raise RuntimeError("Synthetic session did not create its HWNDs")
        initial = parent_conn.recv()
        containers = []
        for hwnd in initial["handles"]:
            foreign = QWindow.fromWinId(hwnd)
            foreign.setFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
            container = QWidget.createWindowContainer(foreign, host)
            layout.addWidget(container)
            containers.append(container)
        host.show()
        app.processEvents()
        parent_conn.send("probe")
        if not parent_conn.poll(15):
            raise RuntimeError("Synthetic session did not report its drop targets")
        after = parent_conn.recv()
        print(json.dumps({"before": initial["before"], "after": after, "host_pid": os.getpid()}))
    finally:
        if child.is_alive():
            parent_conn.send("quit")
            child.join(5)
        if child.is_alive():
            child.terminate()
            child.join(5)
        parent_conn.close()
        host.close()


def _layout_session_child(control, session_conn):
    import ctypes
    from ctypes import wintypes
    from types import SimpleNamespace
    from PyQt6.QtCore import QCoreApplication, QEvent, Qt
    from PyQt6.QtWidgets import QApplication
    from matrix_gui.core.session_window import SessionWindow
    from matrix_gui.core.startup_policy import configure_startup_policy, install_print_gate
    from matrix_gui.core.utils.session_embedding import prepare_embedded_session_window

    install_print_gate()
    configure_startup_policy(debug_output=False)
    app = QApplication([])
    app.setStyleSheet((ROOT / "phoenix/matrix_gui/theme/hive_theme.qss").read_text(encoding="utf-8"))

    class LocalBus:
        def __init__(self):
            self.callbacks = {}

        def on(self, event, callback):
            self.callbacks.setdefault(event, []).append(callback)

        def off(self, event, callback):
            if callback in self.callbacks.get(event, []):
                self.callbacks[event].remove(callback)

        def emit(self, event, **kwargs):
            for callback in list(self.callbacks.get(event, [])):
                callback(**kwargs)

    # Real panels and click handlers, with no transport or server connection.
    window = SessionWindow("fixture", "fixture", "fixture", {"agents": []},
                           session_conn, LocalBus(), None, None, SimpleNamespace(group={}))
    window._hb_timer.stop()
    window.tree._render_tree({"name": "matrix", "universal_id": "matrix", "children": [
        {"name": "matrix_https", "universal_id": "https-1",
         "config": {"ui": {"panel": ["matrix_https"]}}},
        {"name": "matrix_websocket", "universal_id": "wss-1",
         "config": {"ui": {"panel": ["matrix_websocket"]}}},
        {"name": "plain", "universal_id": "plain-1", "config": {}},
        {"name": "long_fixture_agent_name", "universal_id": "other-1", "config": {}},
    ]})
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    hwnd = prepare_embedded_session_window(window)
    window.start_pipe_timer()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.MapWindowPoints.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_void_p, wintypes.UINT]
    user32.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    user32.GetPropW.restype = ctypes.c_void_p

    def snapshot():
        rect = wintypes.RECT()
        parent = user32.GetParent(hwnd)
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        user32.MapWindowPoints(None, parent, ctypes.byref(rect), 2)
        return {
            "native": [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top],
            "qt": list(window.geometry().getRect()),
            "registered": bool(user32.GetPropW(hwnd, "OleDropTargetInterface")),
            "parent": int(parent or 0),
            "visible": window.isVisible(),
        }

    control.send({"hwnd": hwnd, "visible_before_embedding": window.isVisible()})
    try:
        clicks = 0
        while True:
            app.processEvents()
            if not control.poll(0.01):
                continue
            command = control.recv()
            if command == "quit":
                break
            window._poll_conn()  # Exercise the production embedding handshake.
            if command == "click":
                item = window.tree.tree.topLevelItem(0).child(clicks % 4)
                clicks += 1
                window.tree.tree.setCurrentItem(item)
                window.tree._on_tree_item_clicked(item)
            for _ in range(5):
                app.processEvents()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                time.sleep(0.01)
            control.send(snapshot())
    finally:
        window.close()
        session_conn.close()
        control.close()


def _native_layout_probe():
    import multiprocessing
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QLabel, QStackedWidget, QTabWidget, QVBoxLayout, QWidget

    sys.path.insert(0, str(ROOT / "phoenix"))
    from matrix_gui.core.utils.session_embedding import create_embedded_session_container
    app = QApplication([])
    app.setStyleSheet((ROOT / "phoenix/matrix_gui/theme/hive_theme.qss").read_text(encoding="utf-8"))
    host = QWidget()
    host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    host.setGeometry(80, 90, 1100, 750)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(17, 23, 17, 23)
    header = QLabel("Host toolbar")
    header.setFixedHeight(100)
    layout.addWidget(header)
    tabs = QTabWidget()
    tabs.setObjectName("PhoenixSessionTabs")
    tabs.addTab(QWidget(), "Dashboard")
    layout.addWidget(tabs)
    # Production adds sessions to an already shown cockpit. Creating every
    # container before host.show() masks Qt's initial coordinate-system bug.
    host.show()
    app.processEvents()
    ctx = multiprocessing.get_context("spawn")
    control, child_control = ctx.Pipe()
    session_conn, child_session_conn = ctx.Pipe()
    child = ctx.Process(target=_layout_session_child, args=(child_control, child_session_conn))
    child.start()
    child_control.close()
    child_session_conn.close()

    def receive():
        deadline = time.monotonic() + 15
        while not control.poll(0.01):
            app.processEvents()
            if time.monotonic() >= deadline:
                raise TimeoutError("Synthetic session did not report its geometry")
        return control.recv()

    try:
        initial = receive()
        container = create_embedded_session_container(initial["hwnd"])
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(container)
        tabs.setCurrentIndex(tabs.addTab(tab, "Session"))
        tab_layout.activate()
        session_conn.send({"type": "session.embedded", "session_id": "fixture",
                           "parent_win_id": int(container.winId()),
                           "width": container.width(), "height": container.height()})
        samples = []
        sizes = {5: (1000, 740), 10: (1400, 850), 15: (900, 690), 20: (1250, 800)}
        for index in range(25):
            if index in sizes:
                host.resize(*sizes[index])
                app.processEvents()
            if index in (8, 16):
                tabs.setCurrentIndex(0)
                app.processEvents()
                tabs.setCurrentIndex(1)
                app.processEvents()
            control.send("probe" if index == 0 else "click")
            samples.append({"session": receive(),
                            "container_size": [container.width(), container.height()],
                            "scale": container.devicePixelRatioF()})
        stack = tabs.findChild(QStackedWidget)
        margins = stack.contentsMargins()
        print(json.dumps({"initial": initial, "samples": samples,
                          "parent": int(container.winId()),
                          "tab_margins": [margins.left(), margins.top(), margins.right(), margins.bottom()]}))
    finally:
        if child.is_alive():
            control.send("quit")
            child.join(5)
        if child.is_alive():
            child.terminate()
            child.join(5)
        control.close()
        session_conn.close()
        host.close()


class NativeSessionDropTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows OLE drop-target regression")
    def test_embedded_session_keeps_native_drop_target(self):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "windows"
        env["PYTHONPATH"] = str(ROOT / "phoenix")
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--native-probe"],
                                env=env, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout.strip())
        self.assertFalse(data["before"][0]["registered"], "Legacy Qt.SubWindow must reproduce the bug")
        self.assertTrue(data["before"][1]["registered"], "Qt.Window must register with Windows OLE")
        self.assertFalse(data["after"][0]["registered"])
        self.assertTrue(data["after"][1]["registered"], "Cockpit embedding must preserve OLE registration")
        self.assertEqual(data["after"][1]["parent_pid"], data["host_pid"],
                         "Test must embed the session under the other process's native window")

    @unittest.skipUnless(sys.platform == "win32", "Windows native embedding regression")
    def test_agent_clicks_and_host_resize_do_not_shift_session(self):
        env = os.environ.copy()
        env.update(QT_QPA_PLATFORM="windows", PYTHONPATH=str(ROOT / "phoenix"), PYTHONIOENCODING="utf-8")
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--layout-probe"],
                                env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout.strip())
        self.assertFalse(data["initial"]["visible_before_embedding"])
        self.assertEqual(data["tab_margins"], [0, 0, 0, 0], "Outer session frame must add no inset")
        self.assertEqual(len(data["samples"]), 25)
        for index, sample in enumerate(data["samples"]):
            with self.subTest(selection=index):
                session = sample["session"]
                self.assertEqual(session["native"][:2], [0, 0])
                self.assertEqual(session["qt"][:2], [0, 0])
                self.assertEqual(session["qt"][2:], sample["container_size"])
                for actual, logical in zip(session["native"][2:], sample["container_size"]):
                    self.assertAlmostEqual(actual, logical * sample["scale"], delta=1)
                self.assertEqual(session["parent"], data["parent"])
                self.assertTrue(session["registered"], "OLE drop target must survive every layout change")
                self.assertTrue(session["visible"])


if __name__ == "__main__":
    if "--native-probe" in sys.argv:
        _native_probe()
    elif "--layout-probe" in sys.argv:
        _native_layout_probe()
    else:
        unittest.main()
