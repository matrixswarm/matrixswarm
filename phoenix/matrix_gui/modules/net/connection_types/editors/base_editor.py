from abc import ABCMeta, abstractmethod
from PyQt6.QtWidgets import QWidget
import uuid

class EditorABCMeta(type(QWidget), ABCMeta):
    pass

class ConnectionEditorInterface(QWidget, metaclass=EditorABCMeta):

    def __init__(self, parent=None, new_conn=False, default_channel_options=None):
        super().__init__(parent)
        self._is_new = bool(new_conn)
        self._default_channel_options = default_channel_options or []
        self._proto_widget = None
        self._serial_widget = None

    # ---------------------------------------------------------
    # Built-in lifecycle: NEW
    # ---------------------------------------------------------
    def on_create(self):
        """Called ONLY for brand new connections."""
        self._ensure_serial()

    # ---------------------------------------------------------
    # Built-in lifecycle: LOAD
    # ---------------------------------------------------------
    def _load_data(self, data: dict):
        """Internal load handler that guarantees lifecycle correctness."""
        self._is_new = False
        self.on_load(data)

    @abstractmethod
    def on_load(self, data: dict):
        """
        Concrete editors implement this — but cannot touch _is_new.
        Base class sets _is_new = False before calling this.
        """
        pass

    # ---------------------------------------------------------
    # PROTO/SERIAL ENFORCEMENT
    # ---------------------------------------------------------
    def _lock_proto_and_serial(self, proto_widget, serial_widget):
        self._proto_widget = proto_widget
        self._serial_widget = serial_widget

        if self._is_new:
            self._serial_widget.setText(str(self._gen_serial_24()))

        proto_widget.setReadOnly(True)
        serial_widget.setReadOnly(True)

        proto_widget.setStyleSheet("color:#888; background-color:#222;")
        serial_widget.setStyleSheet("color:#888; background-color:#222;")

    def _gen_serial_24(self):
        return uuid.uuid4().hex[:24]

    def _gen_serial_32(self):
        return uuid.uuid4().hex[:32]

    def _ensure_serial(self):
        if not self._serial_widget:
            raise RuntimeError("Serial widget not attached.")
        if not self._serial_widget.text().strip():
            new = self._gen_serial_24()
            self._serial_widget.setText(new)
            return new
        return self._serial_widget.text().strip()

    def _require_proto_and_serial(self):
        proto = self._proto_widget.text().strip()
        serial = self._serial_widget.text().strip()

        if not proto:
            return False, "Protocol is required."

        if not serial:
            return False, "Serial is required."

        if len(serial) not in (8, 16, 24, 32):
            return False, "Serial must be 8, 16, 24, or 32 hex hex digits."

        return True, ""

    def _generate_auto_label(self, proto, data):
        """Create a human-readable label when user does not supply one."""
        try:
            if proto in ("https", "wss"):
                host = data.get("host", "")
                port = data.get("port", "")
                return f"{proto}://{host}:{port}"
            elif proto == "email":
                user = data.get("incoming_username") or data.get("smtp_username") or "email"
                host = data.get("incoming_server") or data.get("smtp_server") or ""
                return f"email:{user}@{host}"
            elif proto == "discord":
                return f"discord:{data.get('channel_id', '')}"
            elif proto == "telegram":
                return f"telegram:{data.get('chat_id', '')}"
            elif proto == "openai":
                k = data.get("api_key", "")
                return f"openai:{k[:8]}..." if k else "openai"
            elif proto == "slack":
                url = data.get("webhook_url", "")
                return f"slack:{url[:8]}..." if url else "slack"
            else:
                return f"{proto}:{self._ensure_serial()}"  # last-resort fallback
        except Exception:
            return f"{proto}:{self._ensure_serial()}"

    # ---------------------------------------------------------
    # Data API
    # ---------------------------------------------------------
    @abstractmethod
    def serialize(self) -> dict:
        pass

    @abstractmethod
    def validate(self) -> tuple[bool, str]:
        pass
