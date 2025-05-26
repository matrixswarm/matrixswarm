import time
from core.class_lib.packet_delivery.interfaces.base_packet import BasePacket

class Packet(BasePacket):
    def __init__(self):
        self._valid = True
        self._payload = {}
        self._error_code = 0
        self._error_msg = ""
        self._packet = None
        self._packet_field_name = "embedded"  # Can be overridden

    def is_valid(self) -> bool:
        return self._valid

    def set_packet(self, packet, field_name="embedded"):
        if self._payload:
            raise RuntimeError("[PACKET][ERROR] set_packet() must be called after set_data()")

        if field_name:
            self._packet_field_name = field_name
        self._packet = packet
        return self

    def set_data(self, data: dict):
        if self._packet:
            raise RuntimeError("[PACKET][ERROR] set_data() must be called before set_packet()")
        try:
            if not data.get("pubkey") or not data.get("bootsig"):
                raise ValueError("Missing 'pubkey' or 'bootsig' in identity payload.")

            self._payload = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "universal_id": data.get("universal_id", "unknown"),
                "pubkey": data["pubkey"],
                "bootsig": data["bootsig"]
            }

            self._error_code = 0
            self._error_msg = ""
        except Exception as e:
            self._valid = False
            self._error_code = 1
            self._error_msg = str(e)

    def get_packet(self) -> dict:
        base = self._payload
        if self._packet and self._packet.is_valid():
            base[self._packet_field_name] = self._packet.get_packet()
        return {
            "type": "notify.identity.register",
            "content": base
        }

    def get_error_success(self) -> int:
        return self._error_code

    def get_error_success_msg(self) -> str:
        return self._error_msg
