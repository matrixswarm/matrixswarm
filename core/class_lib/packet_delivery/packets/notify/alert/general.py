# core/class_lib/packet_delivery/packet/notify/alert/general.py

import time
from core.class_lib.packet_delivery.interfaces.base_packet import BasePacket

class Packet(BasePacket):
    def __init__(self):
        self._valid = True
        self._payload = {}
        self._error_code = 0
        self._error_msg = ""
        self._packet = None

    def is_valid(self) -> bool:
        return self._valid

    def set_packet(self, packet):
        self._packet = packet

    def set_data(self, data: dict):
        try:
            self._payload = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "universal_id": data.get("universal_id", "unknown"),
                "level": data.get("level", "info"),
                "msg": data.get("msg", ""),
                "formatted_msg": f"📣 Swarm Message\n{data.get('msg', '')}",
                "cause": data.get("cause", "unspecified"),
                "origin": data.get("origin", data.get("universal_id", "unknown"))
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
            base["embedded"] = self._packet.get_packet()
        return base

    def get_error_success(self) -> int:
        return self._error_code

    def get_error_success_msg(self) -> str:
        return self._error_msg