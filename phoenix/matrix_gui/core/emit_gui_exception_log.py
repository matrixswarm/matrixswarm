import sys
import traceback
from matrix_gui.core.event_bus import EventBus
from PyQt6.QtWidgets import QMessageBox

def emit_gui_exception_log(label: str, exception: Exception, show_safe_message=False):
    try:

        msg = str(exception).strip() or "⚠️ Unknown GUI error"
        print(f"\n🔥[EXCEPTION][{label}] {msg}")


        # Safe fallback string
        exception_message = str(exception).strip() or "⚠️ Unhandled GUI error (no message)"
        exc_type, exc_value, exc_tb = sys.exc_info()
        trace = traceback.extract_tb(exc_tb) if exc_tb else []

        if not trace:
            trace_info = "[NO TRACEBACK AVAILABLE]"
            file = "unknown"
            line = -1
            function = "unknown"
        else:
            last = trace[-1]
            file = last.filename
            line = last.lineno
            function = last.name
            trace_info = traceback.format_exc()

        payload = {
            "label": label,
            "exception_type": type(exception).__name__,
            "exception_message": exception_message,
            "file": file,
            "line": line,
            "function": function,
            "traceback": trace_info
        }

        print(f"\n[EXCEPTION][{label}] {payload['exception_type']}: {payload['exception_message']}")
        print(f"📁 {file}:{line} in {function}")
        print("🔍 Traceback:\n" + trace_info)

        # emit to Phoenix event bus
        EventBus.emit("gui.log.exception", payload)

        if bool(show_safe_message):
            _safe_show_gui_error(label, exception_message)

    except Exception as fallback:
        print(f"[LOGGING ERROR] Failed to log GUI exception: {fallback}")


def _safe_show_gui_error(title: str, message: str):
    try:
        if not message.strip():
            return
        # message must be plain text
        QMessageBox.critical(None, f"Tripwire GUI — {title}", message)
    except Exception as inner:
        print(f"[FATAL GUI] Could not display message box: {inner}")
