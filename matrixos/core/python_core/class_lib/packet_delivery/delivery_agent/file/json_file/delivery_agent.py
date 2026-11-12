import os
import json
import uuid
import time
import stat
from core.python_core.safe_paths import _component, open_beneath, write_file_at
from core.python_core.class_lib.packet_delivery.utility.security.filesystem_packet_paths import packet_directory
from core.python_core.class_lib.packet_delivery.interfaces.base_delivery_agent import BaseDeliveryAgent
from core.python_core.class_lib.packet_delivery.interfaces.packet_processor import PacketProcessorBase
from core.python_core.mixin.log_method import LogMixin
class DeliveryAgent(BaseDeliveryAgent, LogMixin):
    def __init__(self):
        self._location = None
        self._address = []
        self._packet = None
        self._drop_zone = None
        self._error = None
        self._file_ext = ".json"
        self._filename_prefix = "pk"
        self._custom_metadata = {}
        self._crypto=None
        self._filename_override = None
        self._save_filename=""
        self._sent_packet = "PACKET_NOT_SENT"
        self._location_fd = None

    def set_crypto_handler(self, crypto_handler: PacketProcessorBase):
        self._crypto = crypto_handler
        return self

    def set_identifier(self, name: str):
        _component(name)
        if not name.endswith(self._file_ext):
            name += self._file_ext
        self._filename_override = name
        return self

    def set_metadata(self, metadata: dict):
        self._file_ext = metadata.get("file_ext", self._file_ext)
        self._filename_prefix = metadata.get("prefix", self._filename_prefix)
        self._custom_metadata = metadata
        return self

    def set_location(self, loc):
        new_location = loc.get("path")
        if new_location != self._location:
            self.close()
        self._location = new_location
        return self

    def set_location_fd(self, directory_fd):
        """Pin the configured packet root for this sender's lifetime."""
        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise ValueError("Packet root descriptor is not a directory")
        replacement = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=directory_fd)
        self.close()
        self._location_fd = replacement
        return self

    def close(self):
        if self._location_fd is not None:
            fd, self._location_fd = self._location_fd, None
            os.close(fd)

    def __del__(self):
        try:
            self.close()
        except (AttributeError, OSError):
            pass

    def set_address(self, ids):
        self._address = list(ids) if isinstance(ids, list) else [ids]
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
                with packet_directory(self._location, uid, self._drop_zone, create=True, root_fd=self._location_fd):
                    pass
            self._error = None
        except Exception as e:
            self._error = f"[JSON_FILE][CREATE] Failed: {e}"
        return self

    def get_saved_filename(self) -> str:
        return self._save_filename

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

            try:
                self._crypto.set_logger(self.get_logger())
            except Exception as e:
                pass

            uids = self._address if self._address else [None]
            for uid in uids:

                timestamp = int(time.time())

                try:

                    data = self._crypto.prepare_for_delivery(self._packet)

                    fname = self._filename_override or f"{self._filename_prefix}_{timestamp}_{uuid.uuid4().hex}{self._file_ext}"
                    _component(fname)
                    drop_path = os.path.join(self._location, uid) if uid else self._location
                    if self._drop_zone:
                        drop_path = os.path.join(drop_path, self._drop_zone)
                    full_path = os.path.join(drop_path, fname)

                    # Optional metadata config
                    indent = self._custom_metadata.get("indent", 2)
                    atomic = self._custom_metadata.get("atomic", True)
                    encoded = json.dumps(data, indent=indent).encode("utf-8")
                    with packet_directory(self._location, uid, self._drop_zone, root_fd=self._location_fd) as directory_fd:
                        if atomic:
                            write_file_at(directory_fd, fname, encoded, mode=0o600, durable=True, preserve_mode=False)
                        else:
                            fd = open_beneath(directory_fd, fname, os.O_WRONLY | os.O_CREAT | os.O_NONBLOCK, 0o666)
                            try:
                                info = os.fstat(fd)
                                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                                    raise ValueError("Unsafe packet file")
                                os.ftruncate(fd, 0)
                                with os.fdopen(fd, "wb") as f:
                                    fd = -1
                                    f.write(encoded)
                            finally:
                                if fd >= 0:
                                    os.close(fd)
                    self._sent_packet = data

                    self._save_filename = full_path

                except Exception as e:
                    self._error = f"[DELIVER][WRITE] Failed to write packet: {e}"
                    self.log("Failed to write packet", error=e)

                return self

        except Exception as e:

            self._error = f"[JSON_FILE][DELIVER] Failed: {e}"
            self.log("Failed", error=e)
        return self

    def get_sent_packet(self):
        return self._sent_packet
