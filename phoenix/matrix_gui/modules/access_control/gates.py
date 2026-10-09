"""Guards for legacy paths which have no reviewed AI adapter yet."""
from functools import wraps


def require_normal_mode():
    from .access_control_singleton import AccessControlSingleton
    authority = AccessControlSingleton.get()
    # Normal Mode preserves the manual dispatch policy. In AI Mode an
    # unsupported, unregistered action cannot be authorized by UI state.
    authority.commit("legacy.manual", lambda: None)


def manual_ui_only(method):
    """Guard no-argument UI actions, including direct programmatic calls."""
    @wraps(method)
    def guarded(self):
        # QAction.triggered and QPushButton.clicked carry a checked boolean.
        # Keep this bound slot's arity at zero so Qt discards that signal
        # argument, as it did before these manual handlers were decorated.
        try:
            require_normal_mode()
        except (PermissionError, RuntimeError):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Blocked in AI Mode",
                "This action has no AI adapter yet. Close and reopen the vault in Normal Mode to use it manually.")
            return None
        try:
            return method(self)
        except Exception as error:
            # An exception escaping a Python Qt slot can terminate Phoenix.
            # Report failures from handlers without their own error boundary.
            from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
            emit_gui_exception_log(f"Manual action: {method.__qualname__}", error,
                                   show_safe_message=True)
            return None
    return guarded
