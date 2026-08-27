# Authored by Daniel F MacDonald and ChatGPT aka The Generals
import os
import sys
import time
import json
import base64
import threading
import hashlib
import re

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

from core.python_core.boot_agent import BootAgent
from core.python_core.class_lib.packet_delivery.utility.encryption.config import ENCRYPTION_CONFIG
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from core.python_core.class_lib.logging.logger import Logger

class Agent(BootAgent):
    """
    LogStreamer — tails an agent.log, streams lines back to Matrix via
    ephemeral rpc_handler, supports start_line offsets, and handles rotation.
    """

    # Redaction is deliberately performed here, at the swarm egress boundary.
    # Phoenix must never receive a clear-text secret just because an agent
    # logged a request payload or configuration object.
    _PEM_BEGIN_RE = re.compile(
        r"(?i)-----BEGIN (?:[A-Z0-9 ]*PRIVATE KEY|OPENSSH PRIVATE KEY)-----"
    )
    _PEM_END_RE = re.compile(r"(?i)-----END (?:[A-Z0-9 ]*PRIVATE KEY|OPENSSH PRIVATE KEY)-----")

    @classmethod
    def _redact_text(cls, value, stream=None) -> str:
        """Defend against secrets embedded in free-form or malformed logs."""
        text = str(value)

        # PEM blocks can span many log lines, so remember state per stream.
        pem_active = bool(stream and stream.get("redacting_pem", False))
        if pem_active:
            if cls._PEM_END_RE.search(text):
                stream["redacting_pem"] = False
                return "[REDACTED PEM PRIVATE KEY]"
            return "[REDACTED PEM PRIVATE KEY DATA]"

        if cls._PEM_BEGIN_RE.search(text):
            if stream is not None and not cls._PEM_END_RE.search(text):
                stream["redacting_pem"] = True
            return "[REDACTED PEM PRIVATE KEY]"

        return Logger.redact_text(text)

    def _redact_log_lines(self, lines, stream):
        return [self._redact_text(line, stream) for line in lines]

    def __init__(self):
        super().__init__()
        try:
            self.AGENT_VERSION = "1.2.1"
            cfg = self.tree_node.get("config", {})

            self.interval = int(cfg.get("interval", 2))     # seconds between polls
            self.heartbeat_ttl = int(cfg.get("heartbeat_ttl", 30))
            self.rate_limit = float(cfg.get("rate_limit", 2.0))  # seconds between sends

            self.active_streams = {}

            self.rpc_role=self.tree_node.get("rpc_router_role", "hive.rpc")

            # encryption
            self.key_bytes = None
            if ENCRYPTION_CONFIG.is_enabled():
                swarm_key = ENCRYPTION_CONFIG.get_swarm_key()
                self.key_bytes = base64.b64decode(swarm_key)

        except Exception as e:
            self.log(error=e, block="main_try")

    def post_boot(self):
        self.log(f"{self.NAME} v{self.AGENT_VERSION} – LogStreamer standing guard.")
        threading.Thread(target=self._monitor_sessions, daemon=True).start()

    def _monitor_sessions(self, check_interval: int = 15, threshold: int = None):
        """
        Removes log streams only when every available relay broadcast flag
        has gone missing or stale.

        A Phoenix session can be visible through more than one hive.rpc relay
        (for example, websocket and email egress). One relay not owning the
        session must not tear down a stream that still has another live relay.
        """
        alert_role = self.tree_node.get("rpc_router_role", "hive.rpc")
        freshness = self.heartbeat_ttl if threshold is None else int(threshold)

        while True:
            for sess in list(self.active_streams.keys()):
                if int(time.time()) % 60 == 0:  # every ~60 seconds
                    self.log(f"[DEBUG] Active streams: {len(self.active_streams)}")

                stream = self.active_streams.get(sess)
                if not stream:
                    continue

                fresh_relays, relay_count = self._relay_status_for_session(
                    sess,
                    role=alert_role,
                    threshold=freshness,
                )

                if fresh_relays:
                    stream["active_relays"] = fresh_relays
                    continue

                if relay_count == 0:
                    continue

                age = time.time() - stream.get("created", time.time())
                if age <= freshness:
                    continue

                self.log(
                    f"[SESSION-MONITOR] 🧹 No fresh relays remain for "
                    f"sess={sess}; stopping stream"
                )
                self.cmd_stop_stream_log({"session_id": sess}, None)
            time.sleep(check_interval)

    # ========== COMMAND HANDLERS ==========
    def cmd_stream_log(self, content, packet, identity: IdentityObject = None):
        """Start streaming logs for a session with canonical field names."""
        sess = content.get("session_id")
        token = content.get("token")
        target = content.get("target_agent")
        start_line = int(content.get("start_line", 0))
        follow = bool(content.get("follow", True))

        missing = [k for k, v in {
            "session_id": sess,
            "token": token,
            "target_agent": target,
        }.items() if not v]

        if missing:
            self.log(f"❌ Missing required stream_log fields: {', '.join(missing)}. "
                     f"Got keys={list(content.keys())}")
            return

        log_path = os.path.join(
            self.path_resolution["static_comm_path"],
            target,
            "logs",
            "agent.log"
        )
        if not os.path.exists(log_path):
            self.log(f"[LOG_STREAMER] ❌ No log file for {target} at {log_path}")
            return

        # Stop existing stream for this session if any
        if sess in self.active_streams:
            self.log(f"[STREAM] 🧨 Overwriting stream for sess={sess}")
            self.cmd_stop_stream_log({"session_id": sess}, packet)

        stop_flag = threading.Event()
        t = threading.Thread(
            target=self._stream_loop,
            args=(sess, token, target, start_line, follow, stop_flag),
            daemon=True,
        )
        return_handler = content.get("return_handler", "agent_log_view.update")
        self.active_streams[sess] = {
            "thread": t,
            "stop": stop_flag,
            "token": token,
            "return_handler": return_handler,
            "can_broadcast": False,
            "active_relays": [],
            "redacting_pem": False,
            "log_path": log_path,
            "created": time.time()
        }
        t.start()
        self.log(f"[LOG_STREAMER] 🎬 Streaming started for {target}, sess={sess}, start_line={start_line}")

    def cmd_stop_stream_log(self, content, packet, identity: IdentityObject = None):
        """Stop streaming logs for a session."""
        sess = content.get("session_id")
        if not sess or sess not in self.active_streams:
            return
        self.active_streams[sess]["stop"].set()
        self.active_streams.pop(sess, None)
        self.log(f"[LOG_STREAMER] 🛑 Stopped log stream for sess={sess}")

    def _hash_lines(self, lines: list[str]) -> str:
        """
        Returns a short SHA256 hash of the given log lines.
        """
        blob = "\n".join(lines).encode("utf-8")
        h = hashlib.sha256(blob).hexdigest()
        return h[:12]  # shorten for readability

    def _stream_loop(self, sess, token, target, start_line, follow, stop_flag):

        offset = start_line
        last_inode = None

        try:
            stream = self.active_streams.get(sess)
            if not stream:
                return

            log_path = stream.get("log_path")
            if not log_path or not os.path.exists(log_path):
                self.log(f"[LOG_STREAMER] ❌ Missing log_path for stream {sess}")
                return

            f = open(log_path, "r", encoding="utf-8")
            last_inode = os.fstat(f.fileno()).st_ino

            total_lines = sum(1 for _ in open(log_path, "r", encoding="utf-8"))
            if offset > total_lines:
                offset = total_lines

            while not stop_flag.is_set():
                # Exit if session was reaped
                stream = self.active_streams.get(sess)
                if not stream:
                    self.log(f"[STREAM] 🚪 Session {sess} gone, exiting loop gracefully.")
                    break

                # rotation check
                try:
                    st = os.stat(log_path)
                    if st.st_ino != last_inode:
                        self.log("[LOG_STREAMER] 🔄 Log rotated, reopening...")
                        f.close()
                        f = open(log_path, "r", encoding="utf-8")
                        last_inode = st.st_ino
                        offset = 0
                except FileNotFoundError:
                    time.sleep(self.interval)
                    continue

                f.seek(0)
                lines = f.readlines()
                new_lines = lines[offset:]

                # Gate: Don't allow broadcast until broadcast flag appears
                if not stream.get("can_broadcast", False):
                    fresh_relays, relay_count = self._relay_status_for_session(
                        sess,
                        role=self.rpc_role,
                        threshold=self.heartbeat_ttl,
                    )
                    if relay_count == 0:
                        self.log("No hive.rpc-compatible agents found for 'hive.rpc'.", level="ERROR")
                        return

                    if not fresh_relays:
                        time.sleep(self.interval)
                        continue

                    stream["can_broadcast"] = True
                    stream["active_relays"] = fresh_relays
                    self.log(
                        f"[STREAM] ✅ Fresh broadcast relay(s) detected for "
                        f"sess={sess}: {', '.join(fresh_relays)}; enabling stream."
                    )

                if new_lines:
                    rendered = []
                    for line in new_lines:
                        try:
                            if self.key_bytes:
                                line = Logger.decrypt_log_line(line, self.key_bytes)
                            entry = json.loads(line)
                            safe_entry = Logger.redact_structure(entry)
                            rendered.append(Logger.render_log_line(safe_entry))
                        except Exception:
                            rendered.append(f"[MALFORMED] {line.strip()}")

                    # Structured redaction above protects normal Logger
                    # entries. This second pass covers renderer output and
                    # malformed/free-form lines without touching agent logs on
                    # disk.
                    rendered = self._redact_log_lines(rendered, stream)

                    if self.debug.is_enabled():
                        h = self._hash_lines(rendered)
                        self.log(f"[LOG_STREAMER] 🚀 Broadcasting {len(rendered)} lines hash={h} sess={sess}")

                    self._broadcast_log_lines(token, target, sess, offset, rendered)

                    offset += len(new_lines)

                if not follow:
                    break

                time.sleep(self.rate_limit)

        except Exception as e:
            self.log(f"Error in stream loop", error=e)

    def has_fresh_broadcast_flag(self, relay_uid: str, session_id: str, threshold: int = 30) -> bool:
        """
        Checks whether connected.flag.<session_id> exists and is fresh
        inside the relay agent's broadcast dir.
        """
        base = os.path.join(self.path_resolution["comm_path"], relay_uid, "broadcast")
        flag = os.path.join(base, f"connected.flag.{session_id}")
        if not os.path.exists(flag):
            return False
        age = time.time() - os.path.getmtime(flag)
        if age > threshold:
            self.log(f"[SESSION-MONITOR] ⚠️ Flag stale ({int(age)}s) relay={relay_uid} sess={session_id}")
            return False
        return True

    def _relay_status_for_session(
        self,
        session_id: str,
        role: str = None,
        threshold: int = None,
    ) -> tuple[list[str], int]:
        """Return fresh relay IDs and the number of compatible relays found."""
        relay_role = role or self.rpc_role
        freshness = self.heartbeat_ttl if threshold is None else int(threshold)
        endpoints = list(self.get_nodes_by_role(relay_role))
        fresh_relays = []

        for endpoint in endpoints:
            relay_uid = endpoint.get_universal_id()
            if self.has_fresh_broadcast_flag(relay_uid, session_id, freshness):
                fresh_relays.append(relay_uid)

        return fresh_relays, len(endpoints)

    def _broadcast_log_lines(self, token: str, target: str, sess: str, offset: int, lines: list):
        """
        Streams rendered log lines to Phoenix via crypto_reply.
        Uses BootAgent's unified callback for signing and dispatch.
        """
        try:

            if not lines:
                return

            return_handler = self.active_streams.get(sess, {}).get(
                "return_handler", "agent_log_view.update"
            )

            payload = {
                "universal_id": target,
                "session_id": sess,
                "token": token,
                "start_line": offset,
                "lines": lines,
                "next_offset": offset + len(lines),
                "timestamp": int(time.time()),
            }

            # Send securely via BootAgent's crypto pipeline
            self.crypto_reply(
                response_handler=return_handler,
                payload=payload,
                session_id=sess,
                token=token,
                rpc_role=self.rpc_role
            )

            if self.debug.is_enabled():
                self.log(f"[LOG_STREAMER] Sent {len(lines)} lines to {return_handler} (sess={sess})")

        except Exception as e:
            self.log("[LOG_STREAMER][ERROR] Failed to broadcast log lines", error=e)


if __name__ == "__main__":
    agent = Agent()
    agent.boot()
