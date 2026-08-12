import time, uuid
from matrix_gui.core.class_lib.packet_delivery.interfaces.base_packet import BasePacket

class Packet(BasePacket):
    """
        GUI-side command packet.
        Wraps outbound messages into the same standardized structure that
        Matrix/agents expect (handler, timestamp, content, etc.).
        For internal use by the GUI's OutboundDispatcher.
        """

    def set_data(self, data: dict):
        try:
            # Derive handler if not explicitly given
            handler = data.get("handler")
            self._payload = {
                "timestamp": int(time.time()),
                "content": data.get("content", {}),
            }
            if handler:
                self._payload["handler"] = handler

            self._data = data
            self._error_code = 0
            self._error_msg = ""
        except Exception as e:
            self._valid = False
            self._error_code = 1
            self._error_msg = str(e)
