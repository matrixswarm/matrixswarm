import sys
import traceback
from matrix_gui.core.event_bus import EventBus  # or your actual path

def emit_gui_exception_log(label: str, exception: Exception):
    exc_type, exc_value, exc_tb = sys.exc_info()
    trace = traceback.extract_tb(exc_tb)

    if not trace:
        return  # no traceback

    last = trace[-1]

    payload = {
        "label": label,
        "exception_type": type(exception).__name__,
        "exception_message": str(exception),
        "file": last.filename,
        "line": last.lineno,
        "function": last.name,
        "traceback": traceback.format_exc()
    }

    #Print to terminal for local dev
    print(f"\n[EXCEPTION][{label}] {payload['exception_type']}: {payload['exception_message']}")
    print(f"📁 {payload['file']}:{payload['line']} in {payload['function']}")
    print("🔍 Traceback:\n" + payload["traceback"])

    EventBus.emit("gui.log.exception", payload)
