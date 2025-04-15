# ────────────────────────────────────────────────────────────
# NOTE:
# Matrix’s prime directive is never stored in her own shard. It lives only in Core.
# This ensures that even if her shard is deleted, corrupted, or intercepted,
# Core alone can resurrect her — injecting her identity, role, and mission
# during the spawn process.

# Matrix may randomly self-terminate after a jitter-based interval
# to eliminate predictable pod footprints and reset filesystem metadata.
# Resurrection is triggered externally based on shard expiration or
# absence, allowing Matrix to return with a fresh UUID and pod.
#
# During resurrection, the encrypted shard.json.enc is passed to Core.
# Core decrypts and evaluates the resurrect flag. If True, a new agent is
# spawned and injected with this metadata. The new pod will overwrite the old
# shard with updated values, retaining junk to obscure structure.
#
# Scavenger will only delete the pod if the resurrect flag is False.
# Agents can bootstrap their identity and orientation directly from the shard
# during __init__ if provided with a --bootstrap or environment-based drop.
# ──────────────────────────────────────────────────

# AGENT DIRECTIVE: SINGLE PURPOSE PRINCIPLE
#
# This agent serves one purpose only. It does not reach above, nor below,
# outside its scope, or beyond its responsibility.
#
# It is autonomous, minimal, and obedient to its mission.
# It communicates only with direct neighbors and honors the system hierarchy.
#
# If it fails, it should fail quietly and clean up after itself.
# If it succeeds, it should report simply and continue.
#
# Role: shard_writer
# UUID: Automatically assigned
# ────────────────────────────────────────

# SHARD SHARING PHILOSOPHY
#
# Shard state is strictly scoped per process. Threaded agents (like Matrix, Scavenger)
# share an in-memory ShardGuard within the same process only. There is no cross-process
# memory sharing to avoid race conditions or unsafe mutation.
#
# If an agent requires external communication or persistence, it must:
# - Use Matrix to coordinate (for lineage or spawn control)
# - Use Redis (optional) for TTL-based messaging, counters, or ephemeral signals
# - Use the filesystem (e.g., /sites/orbit/shard_cache/) for durable shared state
#
# This isolates failures, hardens thread security, and ensures pods operate independently
# with clean cleanup and reboot flows.
# ────────────────────────────────────────


import json
import time
import threading
import psutil
from datetime import datetime

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


from agent_src.core.core import CoreAgent

class ScavengerAgent(CoreAgent):
    def __init__(self, enable_vanish=False):
        # Set paths before calling CoreAgent init (which starts threads)
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        self.agents_dir = os.path.join(self.base_dir, "agents")
        self.shard_pool_path = None  # Will be detected in loop
        self.visited_pods = {}
        self.failed_decrypts = {}

        self.resurrection_timers = {}
        self.resurrection_grace = 60  # or 30 seconds, whatever fits

        super().__init__(agent_name="scavenger")

        print(f"[{self.agent_name.upper()}] UUID registered: {self.uuid}")
        print(f"[{self.agent_name.upper()}] Mailbox: {self.worker_mailbox}")

        self.start_worker()
        if enable_vanish:
            self.start_vanish_timer()

        threading.Thread(target=self.run_main_loop, kwargs={"duration": None}, daemon=True).start()
        threading.Thread(target=self.delegated_matrix_watchdog, daemon=True).start()

    def run_main_loop(self, duration=None):
        # Minimal scavenger loop — this agent only cleans up, not monitors others
        while True:
            try:
                self.shard_pool_path = self._detect_shard_pool()
                if not self.shard_pool_path or not os.path.exists(self.shard_pool_path):
                    print(f"[{self.agent_name.upper()}] No shard pool found. Skipping cycle.")
                    time.sleep(60)
                    continue

                with open(self.shard_pool_path, "r") as f:
                    shard_pool = json.load(f)
                active_uuids = {entry.get("uuid") for entry in shard_pool if "uuid" in entry}

                for folder in os.listdir(self.agents_dir):
                    folder_path = os.path.join(self.agents_dir, folder)
                    if not os.path.isdir(folder_path):
                        continue

                    shard_file = os.path.join(folder_path, "shard.json.enc")
                    decrypted = self._decrypt_shard(shard_file) if os.path.exists(shard_file) else None

                    if folder not in active_uuids:
                        if decrypted and decrypted.get("resurrect", False):
                            first_seen = self.resurrection_timers.get(folder)
                            now = time.time()

                            if not first_seen:
                                self.resurrection_timers[folder] = now
                                print(f"[{self.agent_name.upper()}] Grace period started for {folder}")
                                continue

                            if now - first_seen < self.resurrection_grace:
                                print(f"[{self.agent_name.upper()}] Grace period active for {folder}... waiting.")
                                continue

                            # Grace expired — allow cleanup to continue
                            self.resurrection_timers.pop(folder, None)
                            continue

                        if not decrypted:
                            self.failed_decrypts[folder] = self.failed_decrypts.get(folder, 0) + 1
                            if self.failed_decrypts[folder] < 3:
                                print(f"[{self.agent_name.upper()}] Shard decrypt failed for {folder}. Waiting...")
                                continue

                        try:
                            print(f"[{self.agent_name.upper()}] Orphan found: {folder} — cleaning up.")
                            for root, dirs, files in os.walk(folder_path, topdown=False):
                                for name in files:
                                    os.remove(os.path.join(root, name))
                                for name in dirs:
                                    os.rmdir(os.path.join(root, name))
                            os.rmdir(folder_path)
                            print(f"[{self.agent_name.upper()}] Removed: {folder}")
                            self.failed_decrypts.pop(folder, None)
                        except Exception as e:
                            print(f"[{self.agent_name.upper()}] Failed to clean {folder}: {e}")

            except Exception as e:
                print(f"[{self.agent_name.upper()}] Error during sweep: {e}")

            time.sleep(60)

    # Core-level resurrection monitoring, added for Matrix recovery
    def delegated_matrix_watchdog(self):
        while True:
            matrix_dir = os.path.join(self.base_dir, "agents")
            try:
                found = False
                for folder in os.listdir(matrix_dir):
                    folder_path = os.path.join(matrix_dir, folder)
                    shard_file = os.path.join(folder_path, "shard.json.enc")

                    if os.path.exists(shard_file):
                        decrypted = self._decrypt_shard(shard_file)
                        if decrypted and decrypted.get("name") == "matrix":
                            found = True
                            last_seen = self._read_heartbeat_timestamp(folder_path)
                            if self._heartbeat_stale(last_seen):
                                print("[SCAVENGER:MATRIX] Matrix stale. Spawning replacement.")
                                decrypted["resurrect"] = True

                                # Patch defaults
                                decrypted.setdefault("name", "scavenger")
                                decrypted.setdefault("version", "v1")
                                decrypted.setdefault("revision", "r0")

                                # Track revive metadata
                                decrypted["revive_count"] = decrypted.get("revive_count", 0) + 1
                                decrypted["resurrected_by"] = self.uuid
                                decrypted["last_resurrected"] = datetime.utcnow().isoformat()

                                print(f"[SCAVENGER:MATRIX] Patched Directive:\n{json.dumps(decrypted, indent=2)}")

                                self._encrypt_shard(decrypted, shard_file)
                                self.spawn_directive_now(decrypted)

                if not found:
                    print("[SCAVENGER:MATRIX] No matrix shard found in agents. Awaiting mission control.")

            except Exception as e:
                print(f"[SCAVENGER:MATRIX] Watchdog error: {e}")

            time.sleep(60)

    def _read_heartbeat_timestamp(self, folder_path):
        try:
            acid_path = os.path.join(folder_path, "acid.json")
            if os.path.exists(acid_path):
                with open(acid_path, "r") as f:
                    data = json.load(f)
                    return datetime.fromisoformat(data.get("timestamp"))
        except Exception as e:
            print(f"[SCAVENGER] Failed reading timestamp: {e}")
        return None

    def _heartbeat_stale(self, timestamp, threshold=180):  # 3 minutes
        if not timestamp:
            return True
        return (datetime.utcnow() - timestamp).total_seconds() > threshold

    def spawn_directive_now(self, directive):
        # Prevent spawning duplicate agent by name if process is already running
        name = directive.get("name")
        for proc in psutil.process_iter(attrs=["pid", "cmdline"]):
            if proc.info["cmdline"] and any(name in part for part in proc.info["cmdline"]):
                print(f"[{self.agent_name.upper()}] {name} already active (PID {proc.pid}). Skipping spawn.")
                return

        print(f"[{self.agent_name.upper()}] Delegating spawn directive for: {directive.get('name')}")
        super().spawn_directive_now(directive)

if __name__ == "__main__":
    agent = ScavengerAgent()
    print("[SCAVENGER] ScavengerAgent is live.")
    while True:
        time.sleep(10)
