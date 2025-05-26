import time
from core.class_lib.packet_delivery.interfaces.base_packet import BasePacket

class Packet(BasePacket):
    def __init__(self):
        self._valid = True
        self._payload = {}
        self._error_code = 0
        self._error_msg = ""
        self._packet = None
        self._packet_field_name = "embeded"

    def is_valid(self) -> bool:
        return self._valid

    def set_packet(self, packet, field_name="embeded"):
        if field_name:
            self._packet_field_name = field_name

        self._packet = packet
        return self

    def set_data(self, data: dict):
        try:
            required = ["target_universal_id", "command"]
            for r in required:
                if r not in data:
                    raise ValueError(f"Missing required field: {r}")

            cmd = data["command"]
            if not isinstance(cmd, dict) or "type" not in cmd:
                raise ValueError("Command must be a dict with a 'type' field")

            self._payload = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "target_universal_id": data["target_universal_id"],
                "command": cmd,
                "drop_zone": data.get("drop_zone", "incoming"),
                "delivery": data.get("delivery", "file.json_file"),
                "origin": data.get("origin", "unknown")
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
            "type": "register_identity",
            "content": base
        }

    def get_error_success(self) -> int:
        return self._error_code

    def get_error_success_msg(self) -> str:
        return self._error_msg
