"""Native window setup for sessions hosted by another Phoenix process."""

from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtGui import QGuiApplication, QWindow
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
    """Bind native coordinates while preserving a valid owner for session dialogs."""
    parent_win_id, width, height = int(parent_win_id), int(width), int(height)
    if parent_win_id <= 0 or width <= 0 or height <= 0:
        raise ValueError("Embedding requires a native parent and a positive size")
    native_window = window.windowHandle()
    if native_window is None:
        raise RuntimeError("Prepare the session's native window before binding it")

    if QGuiApplication.platformName() == "windows":
        # The cockpit has already reparented the HWND via createWindowContainer.
        # Keep the owning QWindow top-level: QWidget creates dialogs, menus and
        # tooltips with this window as their transient parent. Giving it a
        # QWindow parent makes Qt reject that owner ("must be a top level
        # window"), leaving modal dialogs without the expected relationship.
        #
        # Qt's Windows native-widget embedding path reconciles a top-level
        # QWindow with a WS_CHILD HWND and parent-relative geometry. This is a
        # Windows-QPA property, also used by Qt's QWinWidget implementation:
        # qtproject/qt-solutions/qtwinmigrate/src/qwinwidget.cpp, QWinWidget::init.
        # Apply it to both objects because the native handle already exists.
        if not native_window.isTopLevel():
            raise RuntimeError("A Windows session must be bound before QWindow reparenting")
        property_name = "_q_embedded_native_parent_handle"
        previous_parent = native_window.property(property_name)
        if previous_parent is not None and int(previous_parent) != parent_win_id:
            raise RuntimeError("An embedded session cannot switch cockpit parents")
        window.setProperty(property_name, parent_win_id)
        native_window.setProperty(property_name, parent_win_id)
        # Reapply platform flags after setting the embedding property. Keep
        # Qt.Window: clearing that type makes updateDropSite revoke OLE drops.
        # An embedded child needs no desktop shadow; adding this flag also
        # forces Qt to refresh platform state on the already-created HWND.
        native_window.setFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                               | Qt.WindowType.NoDropShadowWindowHint)
        # Qt defines EmbeddingControl as 79 in qcoreevent.h, but PyQt6 omits
        # its named enum member. Preserve the native frame-cache reset using
        # the Qt event ID instead of looking up the unavailable binding name.
        embedding_control = QEvent.Type(79)
        QCoreApplication.sendEvent(window, QEvent(embedding_control))
    else:
        parent_window = QWindow.fromWinId(parent_win_id)
        if parent_window is None:
            raise RuntimeError("Qt could not wrap the cockpit's native container")
        # Keep the foreign wrapper alive for the lifetime of the session.
        window._embedded_host_window = parent_window
        native_window.setParent(parent_window)

    # This is the one-time owning-widget show; the cockpit container controls
    # subsequent geometry and visibility. Do not rebind on focus or resume.
    # Showing may restore a cached top-level position; normalize afterwards.
    window.show()
    window.setGeometry(0, 0, width, height)
