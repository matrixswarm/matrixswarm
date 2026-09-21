"""Pinned-host SSH delivery for the Matrix SSH ingress agent."""

import hashlib
import json
import posixpath
import queue
import re
import time
import uuid

from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.class_lib.packet_delivery.utility.security.packet_security import wrap_packet_securely
from matrix_gui.modules.net.connector.interfaces.base_connector import BaseConnector
from matrix_gui.modules.railgun.ssh_support import connect_ssh_profile


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MODES = {"one_shot", "persistent"}
_MAX_ENVELOPE_BYTES = 2 * 1024 * 1024


def remote_inbox(universe, universal_id):
    for label, value in (("universe", universe), ("universal_id", universal_id)):
        if not isinstance(value, str) or not _SAFE_COMPONENT.fullmatch(value):
            raise ValueError(f"invalid {label}")
    return posixpath.join(
        "/matrix/universes/static",
        universe,
        "persistent",
        universal_id,
        "comm/incoming",
    )


def recipient_hash(serial):
    if not isinstance(serial, str) or not serial.strip():
        return None
    return hashlib.sha256(
        f"{serial.strip()}matrix-ssh-ingress".encode("utf-8")
    ).hexdigest()


class SSHConnector(BaseConnector):
    """Upload signed outer envelopes by one-shot or persistent pinned SSH."""

    def __init__(self, shared=None):
        super().__init__(shared=shared)
        self.proto = "ssh"
        self._set_channel_name("ssh")
        self.connection = self.agent.get("connection", {}) if self.agent else {}
        self.mode = str(self.connection.get("ssh_mode") or "one_shot").strip().lower()
        if self.mode not in _MODES:
            raise ValueError("SSH delivery mode must be one_shot or persistent")

        self.host = self.connection.get("host")
        self.port = int(self.connection.get("port", 22))
        self.target_uid = self.agent.get("universal_id")
        self.inbox = remote_inbox(self.deployment.get("universe"), self.target_uid)
        self._recipient = recipient_hash(self.agent.get("serial"))
        if not self._recipient:
            raise ValueError("Target MATRIX_SSH serial is required")

        self._client = None
        self._sftp = None
        self._queue = queue.Queue(maxsize=128)
        self._retry = None

    def run(self):
        """Select lifecycle from the registry profile without a second class."""
        try:
            if self.mode == "persistent":
                self.run_loop()
            else:
                self.run_once()
        except Exception as exc:
            print(f"[SSHConnector][ERROR] {exc}")
            self._emit_status("error", self.host, self.port)
        finally:
            self.close()
        print("SSHConnector.run(): thread exiting cleanly.")

    def submit(self, packet):
        """Queue one packet without blocking the GUI dispatcher."""
        if self.mode != "persistent" or self.stopped():
            return False
        try:
            self._queue.put_nowait((uuid.uuid4().hex, packet))
            return True
        except queue.Full:
            self._emit_status("error", self.host, self.port)
            return False

    def run_once(self):
        packet = self._shared.get("packet")
        if packet is None:
            raise ValueError("SSH one-shot launch requires a packet")
        return self.send(packet, transport_id=uuid.uuid4().hex)

    def loop_tick(self):
        if self._retry is None:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                try:
                    self._ensure_connected()
                except Exception as exc:
                    print(f"[SSHConnector][RECONNECT] {exc}")
                    self._emit_status("error", self.host, self.port)
                    self._close_transport()
                    time.sleep(1)
                return True
        else:
            item = self._retry

        transport_id, packet = item
        if self.send(packet, transport_id=transport_id):
            self._retry = None
        else:
            self._retry = item
            if not self.stopped():
                time.sleep(1)
        return True

    def _ensure_connected(self):
        transport = self._client.get_transport() if self._client else None
        if transport is not None and transport.is_active() and self._sftp is not None:
            return
        self._close_transport()
        self._client, _ = connect_ssh_profile(self.connection, timeout=15)
        transport = self._client.get_transport()
        transport.set_keepalive(30)
        self._sftp = self._client.open_sftp()
        self._sftp.stat(self.inbox)
        self._emit_status("connected", self.host, self.port)

    def _secure_envelope(self, packet, transport_id):
        packet_data = packet.get_packet() if hasattr(packet, "get_packet") else packet
        if not isinstance(packet_data, dict):
            raise ValueError("Matrix packet must be a dictionary")
        inner = {
            "matrix_packet": packet_data,
            "ts": int(time.time()),
            "session_id": self.session_id,
            "transport_id": transport_id,
        }
        envelope = wrap_packet_securely(
            inner,
            deployment=self.deployment,
            sign=True,
            encrypt=True,
            target_uid=self.target_uid,
            extra_fields={"hash": self._recipient},
        )
        payload = json.dumps(
            envelope.get_packet(), separators=(",", ":")
        ).encode("utf-8")
        if len(payload) > _MAX_ENVELOPE_BYTES:
            raise ValueError("SSH packet exceeds size limit")
        return payload

    def _upload(self, transport_id, payload):
        self._ensure_connected()
        final_path = posixpath.join(self.inbox, f"{transport_id}.packet")
        temp_path = posixpath.join(self.inbox, f".{transport_id}.{uuid.uuid4().hex}.tmp")
        try:
            self._sftp.stat(final_path)
            return
        except OSError:
            pass
        try:
            with self._sftp.file(temp_path, "wb") as handle:
                handle.write(payload)
                handle.flush()
            inbox_attrs = self._sftp.stat(self.inbox)
            temp_attrs = self._sftp.stat(temp_path)
            inbox_owner = (inbox_attrs.st_uid, inbox_attrs.st_gid)
            temp_owner = (temp_attrs.st_uid, temp_attrs.st_gid)
            if temp_owner != inbox_owner:
                # Root SFTP uploads are root-owned by default. The Matrix SSH
                # agent runs as the universe account and must own the 0600
                # packet before the atomic rename makes it visible.
                self._sftp.chown(temp_path, *inbox_owner)
            self._sftp.chmod(temp_path, 0o600)
            self._sftp.rename(temp_path, final_path)
        except Exception:
            try:
                self._sftp.remove(temp_path)
            except Exception:
                pass
            raise

    def send(self, packet, timeout=10, transport_id=None):
        transport_id = transport_id or uuid.uuid4().hex
        sessions = get_sessions()
        ctx = sessions.get(self.session_id) if sessions else None
        if ctx and hasattr(ctx, "bus"):
            ctx.bus.emit("channel.packet.sent", start_end=1)
        try:
            self._upload(transport_id, self._secure_envelope(packet, transport_id))
            return True
        except Exception as exc:
            print(f"[SSHConnector][SEND][ERROR] {exc}")
            self._emit_status("error", self.host, self.port)
            self._close_transport()
            return False
        finally:
            if ctx and hasattr(ctx, "bus"):
                ctx.bus.emit("channel.packet.sent", start_end=0)

    def _close_transport(self):
        sftp, client = self._sftp, self._client
        self._sftp = None
        self._client = None
        try:
            if sftp:
                sftp.close()
        finally:
            if client:
                client.close()

    def close(self, session_id=None, channel_name=None):
        if self._closed:
            return
        self._closed = True
        self._close_transport()
        self._emit_status("disconnected", self.host, self.port)
