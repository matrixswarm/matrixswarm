from abc import ABCMeta, abstractmethod
from PyQt6.QtWidgets import QWidget

# Hybrid metaclass: combines Qt's QWidget metaclass and ABCMeta
class PanelABCMeta(type(QWidget), ABCMeta):
    pass


class PhoenixPanelInterface(QWidget, metaclass=PanelABCMeta):
    """
    Unified base interface for all Phoenix panels.
    Provides standard lifecycle management and cleanup hooks.
    """

    cache_panel = True

    def __init__(self, session_id, bus, node=None, session_window=None):
        super().__init__(session_window)
        self.session_id = session_id
        self.bus = bus
        self.node = node

        self.session_window = session_window
        self.conn = getattr(session_window, "conn", None)
        self.deployment = getattr(session_window, "deployment", {})

        # optional hook: some panels need timers or persistent UI state
        self._connected = False
        self._timers = []

        # verify subclass compliance
        missing = [
            fn for fn in [
                "_connect_signals", "_disconnect_signals",
                "get_panel_buttons"
            ]
            if not callable(getattr(self, fn, None))
        ]
        if missing:
            raise NotImplementedError(
                f"{self.__class__.__name__} missing required methods: {', '.join(missing)}"
            )

        # Force every subclass to explicitly declare caching behavior
        if not hasattr(self, "cache_panel"):
            raise NotImplementedError(
                f"{self.__class__.__name__} must define class attribute 'cache_panel' "
                f"(e.g., cache_panel = True or cache_panel = False)"
            )

    # --- Lifecycle Events ---
    def is_cached(self) -> bool:
        """Return True if this panel type is marked to be cached."""
        return bool(getattr(self, "cache_panel", True))

    def showEvent(self, event):
        """Auto-connect signals when shown."""
        try:
            if not self._connected:
                self._connect_signals()
                self._connected = True
            if hasattr(self, "_on_show"):
                self._on_show()
        except Exception as e:
            print(f"[{self.__class__.__name__}] showEvent error: {e}")
        super().showEvent(event)

    def hideEvent(self, event):
        """Auto-disconnect signals when hidden."""
        try:
            if self._connected:
                self._disconnect_signals()
                self._connected = False
            if hasattr(self, "_on_hide"):
                self._on_hide()
        except Exception as e:
            print(f"[{self.__class__.__name__}] hideEvent error: {e}")
        super().hideEvent(event)

    def closeEvent(self, event):
        """Full cleanup on panel close."""
        try:
            self._safe_disconnect_all()
            if hasattr(self, "_on_close"):
                self._on_close()
        except Exception as e:
            print(f"[{self.__class__.__name__}] closeEvent error: {e}")
        super().closeEvent(event)

    # --- Unified Safety Helpers ---
    def _safe_disconnect_all(self):
        """Stops timers, detaches signals, clears references."""
        try:
            self._disconnect_signals()
            for t in getattr(self, "_timers", []):
                if t.isActive():
                    t.stop()
                t.deleteLater()
            self._timers.clear()
        except Exception as e:
            print(f"[{self.__class__.__name__}] cleanup failed: {e}")

    # --- Abstract Required Interface ---
    @abstractmethod
    def _connect_signals(self): ...
    @abstractmethod
    def _disconnect_signals(self): ...
    @abstractmethod
    def get_panel_buttons(self): ...
