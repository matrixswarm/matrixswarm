# 🧭 UpdateSentinelAgent
# ╔════════════════════════════════════════════════════════╗
# ║                    🛡 SENTINEL AGENT 🛡                 ║
# ║     Heartbeat Monitor · Resurrection Watch · Sentinel  ║
# ║   Forged in the signal of Hive Zero | v2.1 Directive   ║
# ║ Accepts: scan / detect / respawn / delay / confirm     ║
# ╚════════════════════════════════════════════════════════╝
# 🧭 UpdateSentinelAgent — Hardened Battlefield Version

import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))
import json
import threading
import traceback

from core.class_lib.time_utils.heartbeat_checker import last_heartbeat_delta
from core.utils.swarm_sleep import interruptible_sleep
from core.boot_agent import BootAgent
from core.mixin.ghost_vault import generate_agent_keypair

class Agent(BootAgent):
    def __init__(self):
        super().__init__()

        config = self.tree_node.get("config", {})
        self.matrix_secure_verified=bool(config.get("matrix_secure_verified",0))
        self.watching = config.get("watching", "the Matrix")
        self.universal_id_under_watch = config.get("universal_id_under_watch", False)
        self.target_node = None
        self.time_delta_timeout = config.get("timeout", 60)  # Default 5 min if not set



    def post_boot(self):
        self.log(f"[SENTINEL] Sentinel booted. Monitoring: {self.watching}")

        # Start watch thread
        threading.Thread(target=self.watch_cycle, daemon=True).start()

    def worker_pre(self):
        self.log("[SENTINEL] Sentinel activated. Awaiting signal loss...")

    def worker_post(self):
        self.log("[SENTINEL] Sentinel down. Final watch cycle complete.")

    def watch_cycle(self):

        self.log("[SENTINEL] Watch cycle started.")

        if self.universal_id_under_watch:

            while self.running:

                try:
                    if len(self.security_box)==0:
                        break

                    universal_id = self.security_box.get('node').get("universal_id")

                    if not universal_id:
                        self.log("Target node missing universal_id. Breathing idle.", block="WATCHING")
                        break

                    die_file = os.path.join(self.path_resolution['comm_path'], universal_id, 'incoming', 'die')

                    if os.path.exists(die_file):
                        self.log(f"{universal_id} has die file. Skipping Loop.", block="WATCHING_DIE_FILE")
                        interruptible_sleep(self, 10)
                        continue

                    time_delta = last_heartbeat_delta(self.path_resolution['comm_path'], universal_id)
                    if time_delta is not None and time_delta < self.time_delta_timeout:
                        interruptible_sleep(self, 10)
                        continue

                    try:

                        keychain = {}

                        node = self.security_box.get('node', {})
                        keychain["priv"] = node.get("vault", {}).get("priv", {})
                        keychain["pub"] = node.get("vault", {}).get("identity", {}).get('pub', {})
                        keychain["swarm_key"] = self.swarm_key
                        keychain['private_key'] = node.get("vault", {}).get("private_key")
                        keychain["matrix_pub"] = self.matrix_pub
                        keychain["matrix_priv"] = self.security_box["matrix_priv"]
                        keychain["encryption_enabled"] = int(self.encryption_enabled)
                        keychain["security_box"] = self.security_box.copy()

                        self.spawn_agent_direct(
                            universal_id=universal_id,
                            agent_name=node.get("name"),
                            tree_node=node,
                            keychain=keychain,
                        )
                        self.log(f"{universal_id} respawned successfully.")

                    except Exception as e:
                        self.log(f"failed to spawn agent", error=e, block="keep_alive", level="error")


                except Exception as e:
                    self.log(f"failed to spawn agent", error=e, block="main_try", level="error")

                interruptible_sleep(self, 10)


if __name__ == "__main__":
    agent = Agent()
    agent.boot()
