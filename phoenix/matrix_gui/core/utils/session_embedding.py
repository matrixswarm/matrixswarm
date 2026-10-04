"""Native window setup for sessions hosted by another Phoenix process."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QWindow
from PyQt6.QtWidgets import QLayout, QWidget


def create_embedded_session_container(win_id):
    """Create the native host before a visible tab can show the container."""
    remote_window = QWindow.fromWinId(int(win_id))
    if remote_window is None:
        raise RuntimeError("Qt could not wrap the session's native window")
    remote_window.setFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
    container = QWidget.createWindowContainer(remote_window)
    # QWindowContainer chooses its coordinate system when first shown. If
    # made native after adding it to a visible tab, it keeps applying the
    # cockpit's toolbar/tab offset inside the new native parent as well.
    container.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
    container.winId()
    container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    container.setMinimumSize(800, 600)
    container.setStyleSheet("background-color: #111;")
    return container


def prepare_embedded_session_window(window):
    # The cockpit container owns the size. A changing toolbar/panel minimum
    # must not resize the native child independently of its host.
    if window.layout() is not None:
        window.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
    window.setMinimumSize(0, 0)
    # Qt's Windows updateDropSite excludes Qt.SubWindow. Keep a Qt.Window
    # type so the owning session process registers its OLE drop target before
    # the cockpit reparents the HWND through QWindow.fromWinId().
    window.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
    window.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
    window.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
    window.create()
    return int(window.winId())


def bind_embedded_session_window(window, parent_win_id, width, height):
    """Bind the owning Qt window to its cockpit parent, then show it in place."""
    parent_win_id, width, height = int(parent_win_id), int(width), int(height)
    if parent_win_id <= 0 or width <= 0 or height <= 0:
        raise ValueError("Embedding requires a native parent and a positive size")
    parent_window = QWindow.fromWinId(parent_win_id)
    if parent_window is None:
        raise RuntimeError("Qt could not wrap the cockpit's native container")

    # Reparenting only the HWND in the cockpit leaves this process treating
    # screen coordinates as child coordinates on later layout/resize events.
    # Keep the foreign wrapper alive for the lifetime of the session.
    window._embedded_host_window = parent_window
    window.windowHandle().setParent(parent_window)
    # Showing may restore a cached top-level position; normalize afterwards.
    window.show()
    window.setGeometry(0, 0, width, height)
