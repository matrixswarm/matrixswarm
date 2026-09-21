# Authored by The Generals — Victory Always Edition
"""Durable, double-wrapped SSH ingress for MatrixSwarm."""

import hashlib
import json
import os
import re
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

from core.python_core.boot_agent import BootAgent
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from core.python_core.class_lib.packet_delivery.utility.security.packet_size import guard_packet_size
from core.python_core.class_lib.packet_delivery.utility.security.unwrap_secure_packet import unwrap_secure_packet
from core.python_core.utils.swarm_sleep import interruptible_sleep


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_PACKET_NAME = re.compile(r"^[0-9a-f]{32}\.packet$")
_MAX_PACKET_BYTES = 2 * 1024 * 1024


def _parse_bool(value):
    """Parse persisted booleans without treating the string 'False' as true."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    raise ValueError(f"invalid boolean value: {value!r}")


def persistent_inbox(site_root, universe, universal_id):
    """Return the fixed durable inbox, rejecting path-like identifiers."""
    for label, value in (("universe", universe), ("universal_id", universal_id)):
        if not isinstance(value, str) or not _SAFE_COMPONENT.fullmatch(value):
            raise ValueError(f"invalid {label}")
    if not isinstance(site_root, str) or not site_root.strip():
        raise ValueError("site root is required")
    return (
        Path(site_root).resolve()
        / "universes"
        / "static"
        / universe
        / "persistent"
        / universal_id
        / "comm"
        / "incoming"
    )


def recipient_hash(serial):
    if not isinstance(serial, str) or not serial.strip():
        return None
    return hashlib.sha256(
        f"{serial.strip()}matrix-ssh-ingress".encode("utf-8")
    ).hexdigest()


class Agent(BootAgent):
    """Consume authenticated SSH drop files and relay their inner packet."""

    def __init__(self):
        super().__init__()
        config = self.tree_node.get("config", {})
        self.poll_interval = max(1, int(config.get("poll_interval", 1)))
        self.batch_limit = max(1, min(int(config.get("batch_limit", 32)), 128))
        self.lockdown_state = _parse_bool(config.get("lockdown_state", False))
        self.lockdown_time = int(config.get("lockdown_time", 0))
        self.lockdown_expires = 0

        signing = config.get("security", {}).get("signing", {})
        self.remote_pubkey = signing.get("remote_pubkey")
        self.local_privkey = signing.get("privkey")
        self.recipient_hash = recipient_hash(self.tree_node.get("serial"))

        self.inbox = persistent_inbox(
            self.path_resolution.get("root_path") or os.getenv("SITE_ROOT"),
            self.command_line_args.get("universe"),
            self.command_line_args.get("universal_id"),
        )
        self.inbox.mkdir(mode=0o700, parents=True, exist_ok=True)
        for private_dir in (self.inbox.parents[1], self.inbox.parent, self.inbox):
            try:
                os.chmod(private_dir, 0o700)
            except OSError:
                pass
        self._seen_ids = set()
        self._seen_order = deque(maxlen=2048)
        self._recover_claimed_packets()

        if not all((self.remote_pubkey, self.local_privkey, self.recipient_hash)):
            self.lockdown_state = True
            self.log("[MATRIX_SSH][INIT][ERROR] Missing secure-ingress identity; locked down.")

        self._emit_beacon = self.check_for_thread_poke(
            "worker", timeout=300, emit_to_file_interval=10
        )
        self.log(f"[MATRIX_SSH][INIT] Durable inbox ready: {self.inbox}")

    def _recover_claimed_packets(self):
        """Put files claimed before an unclean stop back in the ready queue."""
        for claimed in self.inbox.glob(".*.processing"):
            packet_id = claimed.name[1:-len(".processing")]
            if not re.fullmatch(r"[0-9a-f]{32}", packet_id):
                continue
            ready = self.inbox / f"{packet_id}.packet"
            try:
                if ready.exists():
                    claimed.unlink()
                else:
                    os.replace(claimed, ready)
            except OSError as exc:
                self.log("[MATRIX_SSH][RECOVERY][ERROR]", error=exc)

    @staticmethod
    def _extract_recipient_hash(outer_packet):
        if not isinstance(outer_packet, dict):
            return None
        signed = outer_packet.get("content")
        if not isinstance(signed, dict):
            return None
        value = signed.get("hash")
        return value.strip() if isinstance(value, str) else None

    def _unwrap_and_forward(self, outer_packet):
        if not guard_packet_size(outer_packet, log=self.log):
            return False
        if self._extract_recipient_hash(outer_packet) != self.recipient_hash:
            self.log("[MATRIX_SSH][REJECT] Recipient hash mismatch.")
            return False

        inner = unwrap_secure_packet(
            outer_packet,
            self.remote_pubkey,
            self.local_privkey,
            logger=self.log,
        )
        matrix_packet = inner.get("matrix_packet") if isinstance(inner, dict) else None
        if not isinstance(matrix_packet, dict):
            self.log("[MATRIX_SSH][REJECT] Missing inner Matrix packet.")
            return False

        packet = self.get_delivery_packet("standard.command.packet")
        packet.set_data({"handler": "cmd_the_source", "content": matrix_packet})
        self.pass_packet(packet, self.get_matrix_universal_id())
        return True

    def _process_inbox(self):
        processed = 0
        for packet_path in sorted(self.inbox.glob("*.packet"))[: self.batch_limit]:
            if not _PACKET_NAME.fullmatch(packet_path.name):
                continue
            claimed = self.inbox / f".{packet_path.stem}.processing"
            try:
                os.replace(packet_path, claimed)
                if packet_path.stem in self._seen_ids:
                    continue
                if claimed.stat().st_size > _MAX_PACKET_BYTES:
                    raise ValueError("SSH packet exceeds size limit")
                outer = json.loads(claimed.read_text(encoding="utf-8"))
                if self._unwrap_and_forward(outer):
                    if len(self._seen_order) == self._seen_order.maxlen:
                        self._seen_ids.discard(self._seen_order[0])
                    self._seen_order.append(packet_path.stem)
                    self._seen_ids.add(packet_path.stem)
                    processed += 1
            except FileNotFoundError:
                continue
            except Exception as exc:
                self.log("[MATRIX_SSH][INGRESS][REJECT]", error=exc)
            finally:
                try:
                    claimed.unlink(missing_ok=True)
                except OSError as exc:
                    self.log("[MATRIX_SSH][INGRESS][CLEANUP]", error=exc)
        if processed:
            self.log(f"[MATRIX_SSH] Relayed {processed} authenticated packet(s).")

    def toggle_perimeter(self, lockdown_state, lockdown_time):
        self.lockdown_state = _parse_bool(lockdown_state)
        self.lockdown_time = max(0, int(lockdown_time))
        self.lockdown_expires = (
            int(time.time()) + self.lockdown_time
            if self.lockdown_state and self.lockdown_time
            else 0
        )

    def cmd_toggle_perimeter(self, content, packet, identity: IdentityObject = None):
        self.toggle_perimeter(
            content.get("lockdown_state", True),
            content.get("lockdown_time", 0),
        )
        self.crypto_reply(
            response_handler=content.get("return_handler"),
            payload={
                "lockdown_state": "Lockdown" if self.lockdown_state else "Open",
                "lockdown_time": self.lockdown_time,
                "lockdown_expires": str(bool(self.lockdown_expires)),
            },
            session_id=content.get("session_id"),
            token=content.get("token"),
            rpc_role=self.tree_node.get("config", {}).get("rpc_router_role", "hive.rpc"),
        )

    def cmd_status(self, content, packet, identity: IdentityObject = None):
        self.crypto_reply(
            response_handler=content.get("return_handler"),
            payload={
                "lockdown_state": "Lockdown" if self.lockdown_state else "Open",
                "inbox": str(self.inbox),
                "poll_interval": self.poll_interval,
            },
            session_id=content.get("session_id"),
            token=content.get("token"),
            rpc_role=self.tree_node.get("config", {}).get("rpc_router_role", "hive.rpc"),
        )

    def worker(self, config=None, identity: IdentityObject = None):
        try:
            self._emit_beacon()
            if self.lockdown_state and self.lockdown_expires:
                if int(time.time()) >= self.lockdown_expires:
                    self.toggle_perimeter(False, 0)
            if not self.lockdown_state:
                self._process_inbox()
        except Exception as exc:
            self.log("[MATRIX_SSH][WORKER][ERROR]", error=exc)
        finally:
            interruptible_sleep(self, self.poll_interval)

    def post_boot(self):
        self.log("[MATRIX_SSH] Secure durable SSH ingress online.")


if __name__ == "__main__":
    Agent().boot()
