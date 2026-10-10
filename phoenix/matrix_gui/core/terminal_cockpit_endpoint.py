"""Opt-in Connect/session adapter. Terminal privately owns approval and policy."""
from pathlib import Path
import os
import sys


def attach(cockpit):
    data_dir = os.environ.get("PHOENIX_TERMINAL_DATA_DIR")
    if not data_dir:
        return None
    # Load only the sibling project's adapter; no arbitrary plugin path.
    root = Path(__file__).resolve().parents[3] / "phoenix_terminal"
    sys.path.insert(0, str(root))
    try:
        from phoenix_terminal.cockpit_sessions import CockpitSessionBackend, CockpitSessionServer
        from phoenix_terminal.bridge.qt_dispatcher import QtBridgeDispatcher
    finally:
        sys.path.pop(0)
    backend = CockpitSessionBackend(cockpit, Path(data_dir))
    dispatcher = QtBridgeDispatcher(backend, timeout_seconds=15)
    dispatcher.setParent(cockpit)
    server = CockpitSessionServer(dispatcher.call, Path(data_dir))
    server.start()
    from PyQt6.QtWidgets import QApplication
    QApplication.instance().aboutToQuit.connect(server.stop)
    # Keep dispatcher and backend alive; only the narrow endpoint is enabled.
    return server, dispatcher, backend
