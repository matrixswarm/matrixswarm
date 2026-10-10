"""Session-scoped SSH egress: encrypted replies in a private durable outbox."""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
import time
import uuid

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

from agents.python_core.matrix_ssh.matrix_ssh import Agent as SSHIngressAgent
from core.python_core.class_lib.packet_delivery.utility.security.packet_security import wrap_packet_securely
from core.python_core.class_lib.packet_delivery.utility.security.packet_size import guard_packet_size
from core.python_core.class_lib.packet_delivery.utility.security.unwrap_secure_packet import unwrap_secure_packet
from core.python_core.utils.swarm_sleep import interruptible_sleep


_SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_PACKET = re.compile(r"^[0-9a-f]{32}\.packet$")
_MAX_BYTES = 2 * 1024 * 1024


class Agent(SSHIngressAgent):
    """Route hive.rpc replies and alerts to authenticated Phoenix SSH sessions."""

    def __init__(self):
        super().__init__()
        cfg = self.tree_node.get("config", {})
        self.poll_interval = min(self.poll_interval, 30)
        self.packet_ttl = max(30, min(int(cfg.get("packet_ttl", 300)), 300))
        self.session_timeout = max(60, min(int(cfg.get("session_timeout", 180)), 900))
        self.max_pending = max(32, min(int(cfg.get("max_pending_packets", 1024)), 4096))
        self.outbox = self.inbox.parent / "outgoing"
        self._private_dir(self.outbox)
        self.broadcast = Path(self.path_resolution["comm_path"]) / self.command_line_args["universal_id"] / "broadcast"
        self.broadcast.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._private_dir(self.broadcast)
        self._sessions = {}
        self._spool_lock = threading.RLock()

    @staticmethod
    def _private_dir(path):
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise PermissionError("SSH egress requires an owned, real directory")
        os.chmod(path, 0o700)
        return path

    def _session_dir(self, session_id):
        if not isinstance(session_id, str) or not _SESSION.fullmatch(session_id):
            raise ValueError("Invalid SSH session ID")
        return self._private_dir(self.outbox / session_id)

    def _active(self, session_id):
        seen = self._sessions.get(session_id)
        return seen is not None and time.monotonic() - seen <= self.session_timeout

    def _pending_count(self):
        return sum(1 for folder in self.outbox.iterdir()
                   if _SESSION.fullmatch(folder.name) and folder.is_dir() and not folder.is_symlink()
                   for item in folder.iterdir() if _PACKET.fullmatch(item.name))

    def _publish(self, payload, session_id, *, kind="packet"):
        if self.lockdown_state or not isinstance(payload, dict):
            return False
        with self._spool_lock:
            if not self._active(session_id):
                return False
            if self._pending_count() >= self.max_pending:
                self.log("[MATRIX_SSH_EGRESS][QUEUE_FULL] Reply was not queued.", level="WARN")
                return False
            directory = self._session_dir(session_id)
            packet_id = uuid.uuid4().hex
            frame = {"kind": kind, "session_id": session_id,
                     "packet_id": packet_id, "payload": payload}
            signed = wrap_packet_securely(
                frame, peer_pub_key_pem=self.remote_pubkey,
                signing_key_obj=self.local_privkey,
                extra_fields={
                    "expires": int(time.time()) + self.packet_ttl,
                    "hash": hashlib.sha256(
                        f"{self.tree_node['serial']}{session_id}matrix-ssh-egress".encode("utf-8")
                    ).hexdigest(),
                },
            )
            raw = json.dumps({"content": signed}, separators=(",", ":")).encode("utf-8")
            if len(raw) > _MAX_BYTES:
                raise ValueError("SSH reply exceeds the transport size limit")
            temporary = directory / f".{packet_id}.tmp"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, directory / f"{packet_id}.packet")
            finally:
                temporary.unlink(missing_ok=True)
            return True

    def _unwrap_and_forward(self, outer):
        # This inbox accepts transport controls only, never Matrix commands.
        if not guard_packet_size(outer, log=self.log):
            return False
        if self._extract_recipient_hash(outer) != self.recipient_hash:
            return False
        control = unwrap_secure_packet(outer, self.remote_pubkey, self.local_privkey, logger=self.log)
        if not isinstance(control, dict):
            return False
        session_id = control.get("session_id")
        if not isinstance(session_id, str) or not _SESSION.fullmatch(session_id):
            return False
        with self._spool_lock:
            action = control.get("action")
            if action == "hello":
                if session_id not in self._sessions and len(self._sessions) >= 64:
                    return False
                self._sessions[session_id] = time.monotonic()
                self._session_dir(session_id)
                flag = self.broadcast / f"connected.flag.{session_id}"
                fd = os.open(flag, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                os.close(fd)
                os.utime(flag, None, follow_symlinks=False)
                return self._publish({}, session_id, kind="ready")
            if action == "ack":
                packet_id = control.get("packet_id")
                if not isinstance(packet_id, str) or not re.fullmatch(r"[0-9a-f]{32}", packet_id):
                    return False
                # An authenticated ACK cannot name another session or arbitrary path.
                target = self.outbox / session_id / f"{packet_id}.packet"
                if target.parent.is_symlink():
                    return False
                target.unlink(missing_ok=True)
                return True
        return False

    def _sweep(self):
        with self._spool_lock:
            for session_id in list(self._sessions):
                if not self._active(session_id):
                    self._sessions.pop(session_id, None)
                    (self.broadcast / f"connected.flag.{session_id}").unlink(missing_ok=True)
            # An agent restart discards the in-memory session leases. Do not
            # leave a previous lease advertising a relay that cannot route yet.
            for flag in self.broadcast.glob("connected.flag.*"):
                session_id = flag.name[len("connected.flag."):]
                if _SESSION.fullmatch(session_id) and not self._active(session_id):
                    flag.unlink(missing_ok=True)
            cutoff = time.time() - self.packet_ttl
            for directory in self.outbox.iterdir():
                if not _SESSION.fullmatch(directory.name) or directory.is_symlink() or not directory.is_dir():
                    continue
                for item in directory.iterdir():
                    if _PACKET.fullmatch(item.name) or re.fullmatch(r"\.[0-9a-f]{32}\.tmp", item.name):
                        if item.lstat().st_mtime < cutoff:
                            item.unlink(missing_ok=True)
                if directory.name not in self._sessions:
                    try:
                        directory.rmdir()
                    except OSError:
                        pass

    def cmd_rpc_route(self, content, packet, identity=None):
        if not isinstance(content, dict):
            return False
        data = packet.get_packet() if hasattr(packet, "get_packet") else packet
        session_id = data.get("session_id") if isinstance(data, dict) else None
        if session_id and session_id != "*":
            return self._publish(content, session_id)
        with self._spool_lock:
            return any([self._publish(content, sid) for sid in list(self._sessions)])

    def cmd_send_alert_msg(self, content, packet, identity=None):
        if not isinstance(content, dict):
            return False
        sender = identity.get_sender_uid() if identity and identity.has_verified_identity() else "swarm"
        message = {
            "handler": "swarm_feed.alert",
            "content": {"origin": sender, "timestamp": time.time(), "id": uuid.uuid4().hex,
                        "formatted_msg": content.get("formatted_msg") or content.get("msg") or "Swarm alert",
                        "level": content.get("level", "info")},
        }
        sealed = wrap_packet_securely(message, peer_pub_key_pem=self.remote_pubkey,
                                      signing_key_obj=self.local_privkey,
                                      serial_num=self.tree_node["serial"])
        return self.cmd_rpc_route(sealed, {})

    def cmd_status(self, content, packet, identity=None):
        with self._spool_lock:
            payload = {"transport": "ssh_egress", "active_sessions": len(self._sessions),
                       "pending_packets": self._pending_count(), "packet_ttl": self.packet_ttl,
                       "lockdown_state": self.lockdown_state}
        return self.crypto_reply(response_handler=content.get("return_handler"), payload=payload,
                                 session_id=content.get("session_id"), token=content.get("token"),
                                 rpc_role="hive.rpc")

    def worker(self, config=None, identity=None):
        try:
            self._emit_beacon()
            if self.lockdown_state and self.lockdown_expires and time.time() >= self.lockdown_expires:
                self.toggle_perimeter(False, 0)
            self._sweep()
            if not self.lockdown_state:
                self._process_inbox()
        except Exception as exc:
            self.log("[MATRIX_SSH_EGRESS][WORKER][ERROR]", error=exc)
        finally:
            interruptible_sleep(self, self.poll_interval)

    def post_boot(self):
        self.log("[MATRIX_SSH_EGRESS] Private SSH reply outbox online.")


if __name__ == "__main__":
    Agent().boot()
