import os
import json
import time
from core.class_lib.packet_delivery.interfaces.base_delivery_agent import BaseDeliveryAgent

class DeliveryAgent(BaseDeliveryAgent):
    def __init__(self):
        self._location = None
        self._address = []
        self._packet = None
        self._drop_zone = None
        self._error = None

    def set_location(self, loc):
        self._location = loc.get("path")
        return self

    def set_address(self, ids):
        self._address = ids if isinstance(ids, list) else [ids]
        return self

    def set_packet(self, packet):
        self._packet = packet
        return self

    def set_drop_zone(self, drop):
        self._drop_zone = drop.get("drop")
        return self

    def get_agent_type(self):
        return "filesystem"

    def get_error_success(self):
        return 1 if self._error else 0

    def get_error_success_msg(self):
        return self._error or "OK"

    def create_loc(self):
        try:
            if not self._location:
                self._error = "[JSON_FILE][ERROR] No base location set"
                return self
            for uid in self._address:
                base_path = os.path.join(self._location, uid)
                if self._drop_zone:
                    base_path = os.path.join(base_path, self._drop_zone)
                os.makedirs(base_path, exist_ok=True)
            self._error = None
        except Exception as e:
            self._error = f"[JSON_FILE][CREATE] Failed: {e}"
        return self

    def deliver(self, create=True):
        if create:
            self.create_loc()

        if self._error:
            return self

        try:
            if not self._packet:
                self._error = "[JSON_FILE][DELIVER] No packet assigned"
                return self

            data = self._packet.get_packet()
            if not isinstance(data, dict):
                self._error = "[JSON_FILE][DELIVER] Packet data invalid"
                return self

            for uid in self._address:
                drop_path = os.path.join(self._location, uid)
                if self._drop_zone:
                    drop_path = os.path.join(drop_path, self._drop_zone)
                os.makedirs(drop_path, exist_ok=True)

                fname = f"alert_{int(time.time())}.msg"
                full_path = os.path.join(drop_path, fname)

                with open(full_path, "w") as f:
                    json.dump(data, f, indent=2)

        except Exception as e:
            self._error = f"[JSON_FILE][DELIVER] Failed: {e}"

        return self
