#Authored by Daniel F MacDonald and ChatGPT
# ╔════════════════════════════════════════════════════════╗
# ║               🧹 SCAVENGER AGENT 🧹                    ║
# ║   Runtime Sweeper · Pod Watchdog · Tombstone Handler   ║
# ║   Brought online under blackout protocol | Rev 1.8      ║
# ║   Monitors: /pod/* | Deletes: expired / orphaned nodes ║
# ╚════════════════════════════════════════════════════════╝
# 🧹 FINAL FULL HIVE-CORRECTED SCAVENGERAGENT v3.1 🧹
# Using ONLY post_boot(), NEVER manual boot()

import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))
import time
import json
import shutil
import threading
import psutil

from core.boot_agent import BootAgent
from core.class_lib.file_system.util.json_safe_write import JsonSafeWrite
from core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    def __init__(self):
        super().__init__()

        self.orbits = {}
        self.watch_path = os.path.join(self.path_resolution['comm_path'], self.command_line_args['universal_id'], "payload")
        os.makedirs(self.watch_path, exist_ok=True)

    def post_boot(self):
        try:
            self.log("[SCAVENGER] Online. Scanning the battlefield for tombstones...")
            threading.Thread(target=self.safe_command_listener, daemon=True).start()
            threading.Thread(target=self.safe_scavenger_sweep, daemon=True).start()
        except Exception as e:
            self.log(f"[SCAVENGER][POST-BOOT ERROR] {e}")

    def worker_pre(self):
        self.log("[SCAVENGER] Agent activated. Monitoring for cleanup ops.")

    def worker_post(self):
        self.log("[SCAVENGER] Shutdown confirmed. Sweep logs complete.")

    def safe_command_listener(self):
        try:
            self.command_listener()
        except Exception as e:
            self.log(f"[SCAVENGER][COMMAND LISTENER CRASH] {e}")

    def safe_scavenger_sweep(self):
        try:
            self.scavenger_sweep()
        except Exception as e:
            self.log(f"[SCAVENGER][SWEEP CRASH] {e}")

    def command_listener(self):
        while self.running:
            try:
                if not os.path.exists(self.watch_path):
                    time.sleep(2)
                    continue
                for fname in os.listdir(self.watch_path):
                    if not fname.endswith(".cmd"):
                        continue
                    universal_id = fname.replace("scavenge_", "").replace("kill_", "").replace(".cmd", "")
                    full_path = os.path.join(self.watch_path, fname)
                    self.execute_stop(universal_id, annihilate="scavenge" in fname)
                    os.remove(full_path)
            except Exception as e:
                self.log(f"[SCAVENGER][COMMAND ERROR] {e}")
            time.sleep(2)

    def execute_stop(self, universal_id, annihilate=True):
        comm_path = os.path.join(self.path_resolution['comm_path'], universal_id)
        die_path = os.path.join(comm_path, "incoming", "die")
        JsonSafeWrite.safe_write(die_path, "terminate")
        self.log(f"[SCAVENGER] Sent die signal to {universal_id}")
        status = "pause_requested"
        self.send_confirmation(universal_id, status)
        self.notify_matrix_to_verify(universal_id)

    def scavenger_sweep(self):
        self.log("[SCAVENGER] Background sweep active. Scanning every 5 minutes...")
        while self.running:
            try:
                now = time.time()
                pod_root = self.path_resolution["pod_path"]
                comm_root = self.path_resolution["comm_path"]

                if not os.path.exists(pod_root) or not os.path.exists(comm_root):
                    self.log("[SCAVENGER][WARNING] Pod or Comm path missing. Skipping sweep.")
                    interruptible_sleep(self, 120)
                    continue

                #Loop through the pod looking for boot.json to extract --job [identity train]
                for uuid in os.listdir(pod_root):
                    try:
                        pod_path = os.path.join(pod_root, uuid)
                        boot_path = os.path.join(pod_path, "boot.json")

                        if not os.path.isfile(boot_path):
                            continue

                        with open(boot_path, "r") as f:
                            boot_data = json.load(f)
                            universal_id = boot_data.get("universal_id")
                            cmdline_target = boot_data.get("cmd", [])

                        if not universal_id or not cmdline_target:
                            continue

                        comm_path = os.path.join(comm_root, universal_id)
                        tombstone_comm = os.path.join(comm_path, "incoming", "tombstone")
                        tombstone_pod = os.path.join(pod_path, "tombstone")

                        tombstone_paths = [tombstone_comm, tombstone_pod]
                        tombstone_found = False
                        tombstone_age_ok = False

                        for tomb in tombstone_paths:
                            if os.path.exists(tomb):
                                tombstone_found = True
                                age = now - os.path.getmtime(tomb)
                                if age >= 300:
                                    tombstone_age_ok = True
                                    break

                        if not tombstone_found or not tombstone_age_ok:
                            continue

                        still_alive = False
                        for proc in psutil.process_iter(['cmdline']):
                            try:
                                if proc.info['cmdline'] == cmdline_target:
                                    still_alive = True
                                    break
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                continue

                        if still_alive:
                            self.log(f"[SCAVENGER][WARNING] Agent {universal_id} still breathing by cmdline. Delaying sweep.")
                            continue

                        self.log(f"[SCAVENGER] Sweeping corpse: {universal_id} (UUID {uuid})")
                        if os.path.exists(pod_path):
                            shutil.rmtree(pod_path)
                        if os.path.exists(comm_path):
                            shutil.rmtree(comm_path)

                        self.send_confirmation(universal_id, status="terminated")

                    except Exception as e:
                        self.log(f"[SCAVENGER][SWEEP-UUID-ERROR] {e}")

            except Exception as e:
                self.log(f"[SCAVENGER][SWEEP-MAIN-ERROR] {e}")
            interruptible_sleep(self, 120)

    def send_confirmation(self, universal_id, status):
        outbox = os.path.join(self.path_resolution['comm_path'], "matrix", "outbox")
        os.makedirs(outbox, exist_ok=True)
        payload = {
            "status": status,
            "universal_id": universal_id,
            "timestamp": time.time(),
            "message": f"{universal_id} {status} by Scavenger."
        }
        fpath = os.path.join(outbox, f"reaper_{universal_id}.json")
        with open(fpath, "w") as f:
            json.dump(payload, f, indent=2)
        self.log(f"[SCAVENGER] Confirmed: {universal_id} ➔ {status}")

    def notify_matrix_to_verify(self, universal_id):
        verify_path = os.path.join(self.path_resolution['comm_path'], "matrix", "outbox", f"verify_{universal_id}.json")
        payload = {
            "type": "verify_branch",
            "universal_id": universal_id,
            "origin": self.command_line_args.get("universal_id", "unknown"),
            "timestamp": time.time(),
            "status": "post_kill"
        }
        with open(verify_path, "w") as f:
            json.dump(payload, f, indent=2)
        self.log(f"[SCAVENGER] Verification request sent for: {universal_id}")

if __name__ == "__main__":
    agent = Agent()
    agent.boot()