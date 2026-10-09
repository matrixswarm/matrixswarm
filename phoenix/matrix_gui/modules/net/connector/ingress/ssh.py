"""Read session-scoped swarm replies through pinned SSH and authenticated controls."""

from collections import deque
import hashlib
import json
import posixpath
import re
import stat
import time
import uuid

from matrix_gui.core.connector_bus import ConnectorBus
from matrix_gui.core.class_lib.packet_delivery.utility.encryption.utility.unwrap_secure_packet import unwrap_secure_packet
from matrix_gui.core.class_lib.packet_delivery.utility.security.packet_security import wrap_packet_securely
from matrix_gui.modules.net.connector.egress.ssh import SSHConnector


_SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_PACKET = re.compile(r"^([0-9a-f]{32})\.packet$")
_MAX_BYTES = 2 * 1024 * 1024


class SSHIngressConnector(SSHConnector):
    """Poll even in one-shot mode; that mode closes SSH after each poll."""

    @property
    def _connected_status(self):
        return "connected" if time.monotonic() - self._last_verified < 60 else "connecting"

    def __init__(self, shared=None):
        super().__init__(shared)
        if not isinstance(self.session_id, str) or not _SESSION.fullmatch(self.session_id):
            raise ValueError("A safe Phoenix session ID is required for SSH reception")
        self.proto = "ssh_egress"
        self._set_channel_name("ssh_egress")
        self.outbox = posixpath.join(posixpath.dirname(self.inbox), "outgoing", self.session_id)
        self._message_hash = hashlib.sha256(
            f"{self.agent['serial']}{self.session_id}matrix-ssh-egress".encode("utf-8")
        ).hexdigest()
        signing = self.deployment.get("certs", {}).get(self.target_uid, {}).get("signing", {})
        self._peer_key = signing.get("pubkey")
        self._private_key = signing.get("remote_privkey")
        if not self._peer_key or not self._private_key:
            raise ValueError("SSH egress signing identity is missing")
        self.poll_interval = max(1, min(int(self.connection.get("poll_interval", 1)), 30))
        self.batch_limit = max(1, min(int(self.connection.get("batch_limit", 32)), 128))
        self._last_hello = 0.0
        self._last_verified = float("-inf")
        self._next_poll = 0.0
        self._seen = set()
        self._seen_order = deque(maxlen=2048)
        self._acks = {}

    def run(self):
        try:
            self.run_loop()
        finally:
            self.close()

    def _control(self, action, *, packet_id=None, transport_id=None):
        transport_id = transport_id or uuid.uuid4().hex
        body = {"action": action, "session_id": self.session_id, "transport_id": transport_id}
        if packet_id is not None:
            body["packet_id"] = packet_id
        envelope = wrap_packet_securely(
            body, deployment=self.deployment, target_uid=self.target_uid,
            sign=True, encrypt=True, extra_fields={"hash": self._recipient},
        )
        payload = json.dumps(envelope.get_packet(), separators=(",", ":")).encode("utf-8")
        self._upload(transport_id, payload)

    def _acknowledge(self):
        for packet_id, transport_id in list(self._acks.items()):
            self._control("ack", packet_id=packet_id, transport_id=transport_id)
            del self._acks[packet_id]

    def _poll(self):
        try:
            entries = self._sftp.listdir_attr(self.outbox)
        except FileNotFoundError:
            return
        processed = 0
        for attrs in sorted(entries, key=lambda value: value.filename):
            match = _PACKET.fullmatch(attrs.filename)
            if not match or not stat.S_ISREG(attrs.st_mode):
                continue
            if processed >= self.batch_limit or self.stopped():
                break
            processed += 1
            if not 0 < attrs.st_size <= _MAX_BYTES:
                continue
            path = posixpath.join(self.outbox, attrs.filename)
            try:
                with self._sftp.file(path, "rb") as handle:
                    raw = handle.read(_MAX_BYTES + 1)
            except FileNotFoundError:
                continue
            if len(raw) > _MAX_BYTES:
                continue
            try:
                outer = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(outer, dict) or not isinstance(outer.get("content"), dict):
                continue
            if outer["content"].get("hash") != self._message_hash:
                continue
            frame = unwrap_secure_packet(outer, self._peer_key, self._private_key, logger=print)
            packet_id = match[1]
            if (not isinstance(frame, dict) or frame.get("session_id") != self.session_id
                    or frame.get("packet_id") != packet_id):
                continue
            if packet_id not in self._seen:
                if frame.get("kind") == "packet":
                    payload = frame.get("payload")
                    if not isinstance(payload, dict) or not isinstance(payload.get("serial"), str):
                        continue
                    ConnectorBus.get(self.session_id).emit(
                        "inbound.raw", session_id=self.session_id, channel=self.target_uid,
                        source=self.target_uid, payload=payload,
                        ts=outer["content"]["timestamp"],
                    )
                elif frame.get("kind") != "ready":
                    continue
                if len(self._seen_order) == self._seen_order.maxlen:
                    self._seen.discard(self._seen_order[0])
                self._seen_order.append(packet_id)
                self._seen.add(packet_id)
            # Delete only through a signed ACK bound to this session and packet.
            self._acks.setdefault(packet_id, uuid.uuid4().hex)
            self._last_verified = time.monotonic()

    def loop_tick(self):
        if time.monotonic() < self._next_poll:
            return not self.stopped()
        try:
            self._ensure_connected()
            now = time.monotonic()
            if now - self._last_hello >= 30:
                self._control("hello")
                self._last_hello = now
            self._acknowledge()
            self._poll()
            self._acknowledge()
            self._emit_status(self._connected_status, self.host, self.port)
        except Exception as exc:
            print(f"[SSHIngressConnector][RECONNECT] {type(exc).__name__}: {exc}")
            self._emit_status("error", self.host, self.port)
            self._last_hello = 0.0
            self._last_verified = float("-inf")
            self._close_transport()
        finally:
            self._next_poll = time.monotonic() + self.poll_interval
            if self.mode == "one_shot":
                self._close_transport()
        return not self.stopped()

    def send(self, packet, timeout=10, transport_id=None):
        # Reception controls are internal; application commands use matrix_ssh.
        return False
