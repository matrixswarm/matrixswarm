# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import os
import sys
import time
import json
import base64
import threading
from pathlib import Path

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

from matrixswarm.core.boot_agent import BootAgent
from matrixswarm.core.utils.swarm_sleep import interruptible_sleep
from matrixswarm.core.class_lib.packet_delivery.utility.encryption.config import ENCRYPTION_CONFIG
from matrixswarm.core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from matrixswarm.core.class_lib.logging.logger import Logger


class Agent(BootAgent):
    """
    LogSentinel — tails an agent.log, streams lines back to Matrix via
    ephemeral rpc_handler, supports start_line offsets, and handles rotation.
    """

    def __init__(self):
        super().__init__()
        try:
            self.AGENT_VERSION = "1.1.0"
            cfg = self.tree_node.get("config", {})

            self.interval = int(cfg.get("interval", 2))     # seconds between polls
            self.heartbeat_ttl = int(cfg.get("heartbeat_ttl", 30))
            self.rate_limit = float(cfg.get("rate_limit", 2.0))  # seconds between sends

            self.active_streams = {}  # {session_id: {...}}
            self.log_path = None

            # decryption
            self.key_bytes = None
            if ENCRYPTION_CONFIG.is_enabled():
                swarm_key = ENCRYPTION_CONFIG.get_swarm_key()
                self.key_bytes = base64.b64decode(swarm_key)

            self._emit_beacon = self.check_for_thread_poke("_stream_loop", timeout=30, emit_to_file_interval=10)

        except Exception as e:
            self.log(error=e, block="main_try")

    def post_boot(self):
        self.log(f"{self.NAME} v{self.AGENT_VERSION} – LogSentinel standing guard.")

    # ========== COMMAND HANDLERS ==========

    def cmd_stream_log(self, content, packet, identity: IdentityObject = None):
        """Start streaming logs for a session."""
        sess = content.get("session_id")
        rpc  = content.get("rpc_handler")
        target = content.get("target_agent")
        start_line = int(content.get("start_line", 0))
        follow = bool(content.get("follow", True))

        if not (sess and rpc and target):
            self.log("[LOGSENTINEL] ❌ Missing required stream_log fields.")
            return

        self.log_path = os.path.join(
            self.path_resolution["comm_path"], target, "logs", "agent.log"
        )
        if not os.path.exists(self.log_path):
            self.log(f"[LOGSENTINEL] ❌ No log file for {target}")
            return

        # Stop existing stream if present
        self.cmd_stop_stream_log({"session_id": sess}, packet)


        stop_flag = threading.Event()
        t = threading.Thread(
            target=self._stream_loop,
            args=(sess, rpc, target, start_line, follow, stop_flag),
            daemon=True,
        )
        self.active_streams[sess] = {"thread": t, "stop": stop_flag, "rpc": rpc}
        t.start()
        self.log(f"[LOGSENTINEL] 🎬 Streaming started for {target}, sess={sess}, start_line={start_line}")

    def cmd_stop_stream_log(self, content, packet, identity: IdentityObject = None):
        """Stop streaming logs for a session."""
        sess = content.get("session_id")
        if not sess or sess not in self.active_streams:
            return
        self.active_streams[sess]["stop"].set()
        self.active_streams.pop(sess, None)
        self.log(f"[LOGSENTINEL] 🛑 Stopped log stream for sess={sess}")

    # ========== INTERNAL STREAMER ==========

    def _stream_loop(self, sess, rpc, target, start_line, follow, stop_flag):
        offset = start_line
        last_inode = None
        self._emit_beacon()
        try:
            f = open(self.log_path, "r", encoding="utf-8")
            last_inode = os.fstat(f.fileno()).st_ino

            # if requested start_line beyond EOF, clamp
            total_lines = sum(1 for _ in open(self.log_path, "r", encoding="utf-8"))
            if offset > total_lines:
                offset = total_lines

            while not stop_flag.is_set():
                # rotation check
                try:
                    st = os.stat(self.log_path)
                    if st.st_ino != last_inode:
                        self.log("[LOGSENTINEL] 🔄 Log rotated, reopening...")
                        f.close()
                        f = open(self.log_path, "r", encoding="utf-8")
                        last_inode = st.st_ino
                        offset = 0
                except FileNotFoundError:
                    time.sleep(self.interval)
                    continue

                f.seek(0)
                lines = f.readlines()
                new_lines = lines[offset:]

                if new_lines:
                    rendered = []
                    for line in new_lines:
                        try:
                            if self.key_bytes:
                                line = Logger.decrypt_log_line(line, self.key_bytes)
                            entry = json.loads(line)
                            rendered.append(Logger.render_log_line(entry))
                        except Exception:
                            rendered.append(f"[MALFORMED] {line.strip()}")

                    payload = {
                        "handler": rpc,
                        "content": {
                            "universal_id": target,
                            "session_id": sess,
                            "start_line": offset,
                            "lines": rendered,
                            "next_offset": offset + len(new_lines),
                            "timestamp": int(time.time()),
                        },
                    }
                    self.cmd_broadcast(payload, packet=None)
                    offset += len(new_lines)

                if not follow:
                    break

                time.sleep(self.rate_limit)

        except Exception as e:
            self.log(f"[LOGSENTINEL] Error in stream loop", error=e)

        finally:
            if sess in self.active_streams:
                self.active_streams.pop(sess, None)
            try:
                f.close()
            except:
                pass


if __name__ == "__main__":
    agent = Agent()
    agent.boot()
