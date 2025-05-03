# 🧭 UpdateSentinelAgent
# Author: ChatGPT (under orders from General Daniel F. MacDonald)
# ╔════════════════════════════════════════════════════════╗
# ║                    🛡 SENTINEL AGENT 🛡                 ║
# ║     Heartbeat Monitor · Resurrection Watch · Sentinel  ║
# ║   Forged in the signal of Hive Zero | v2.1 Directive   ║
# ║ Accepts: scan / detect / respawn / delay / confirm     ║
# ╚════════════════════════════════════════════════════════╝
# 🧭 UpdateSentinelAgent — Hardened Battlefield Version
import sys
import os
import time
import json
import threading
import traceback

from agent.core.class_lib.time_utils.heartbeat_checker import last_heartbeat_delta
from agent.core.utils.swarm_sleep import interruptible_sleep
from agent.core.boot_agent import BootAgent

class SentinelAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.path_resolution=path_resolution
        self.command_line_args=command_line_args
        config = tree_node.get("config", {})
        self.watching = config.get("watching", "the Matrix")
        self.universal_id = config.get("universal_id", None)
        self.target_node = None
        self.time_delta_timeout = config.get("timeout", 30)  # Default 5 min if not set


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
        while self.running:

            if self.universal_id:

                try:
                    if self.target_node is None:
                        response = self.receive_node_response(self.universal_id)
                        if response is not None:
                            self.target_node = {k: v for k, v in response.items()}
                            self.log(self.target_node)
                        interruptible_sleep(self, 5)
                        continue

                    universal_id = self.target_node.get("universal_id")

                    if not universal_id:
                        self.log("[SENTINEL][WATCH] Target node missing universal_id. Breathing idle.")
                        interruptible_sleep(self, 5)
                        continue

                    die_file = os.path.join(self.path_resolution['comm_path'], universal_id, 'incoming', 'die')

                    if os.path.exists(die_file):
                        self.log(f"[SENTINEL][BLOCKED] {universal_id} has die file.")
                        interruptible_sleep(self, 10)
                        continue

                    time_delta = last_heartbeat_delta(self.path_resolution['comm_path'], universal_id)
                    if time_delta is not None and time_delta < self.time_delta_timeout:
                        interruptible_sleep(self, 10)
                        continue

                    self.spawn_agent_direct(
                        universal_id=universal_id,
                        agent_name=self.target_node.get("name"),
                        tree_node=self.target_node
                    )
                    self.log(f"[SENTINEL][SPAWNED] {universal_id} respawned successfully.")



                except Exception as e:
                    tb = traceback.format_exc()
                    self.log(f"[SENTINEL][WATCH-ERROR] {e}")
                    self.log(f"[SENTINEL][TRACEBACK]\n{tb}")
                    interruptible_sleep(self, 30)

            interruptible_sleep(self, 10)

    def receive_node_response(self, universal_id):
        incoming_path = os.path.join(self.path_resolution['comm_path'], self.command_line_args.get("universal_id", "sentinel"), "incoming")
        if not os.path.exists(incoming_path):
            return None

        # 🔥 If no Matrix response, check local tree file
        agent_tree_file = os.path.join(self.path_resolution['comm_path'], universal_id, "agent_tree.json")
        if os.path.exists(agent_tree_file):
            try:
                with open(agent_tree_file, "r") as f:
                    node = json.load(f)
                self.log(f"[SENTINEL] Loaded agent_tree.json for {universal_id}.")
                return node
            except Exception as e:
                self.log(f"[SENTINEL][TREE-ERROR] {e}")
                return None

        return None

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = SentinelAgent(path_resolution, command_line_args)
    agent.boot()
