import sys
import os
import json
import time
import psutil


if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])

from agent.core.boot_agent import BootAgent
from agent.core.tree_parser import TreeParser
from agent.core.core_spawner import CoreSpawner

class LoggerAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.orbits = {}  # 💥 required for tracking spawned chil

    def pre_boot(self):
        self.log("[LOGGER] Pre-boot check passed.")

    def post_boot(self):
        self.log("[LOGGER] Sending tree request to Matrix.")

    def worker(self):
        self.log("[LOGGER] LoggerAgent is now running.")
        while self.running:
            self.log("[LOGGER] Logging timestamp...")
            time.sleep(10)


    def process_command(self, command):
        action = command.get("action")
        if action == "log_message":
            msg = command.get("message", "(no message)")
            self.log(f"[COMMAND-LOG] {msg}")
        elif action == "die":
            self.log("[COMMAND] Received die command.")
            self.running = False
        elif action == "update_delegates":
            self.log(f"[COMMAND] Delegate update received. Saving tree and spawning.")
            tree_path = os.path.join(
                self.path_resolution["comm_path"],
                self.command_line_args["permanent_id"],
                "agent_tree.json"
            )
            with open(tree_path, "w") as f:
                json.dump(command["tree_snapshot"], f, indent=2)

            # 💥 Right here — the critical line:
            self.spawn_manager()

        self.log(f"[COMMAND] Received command: {command}. WORK YOU SOB!! DO IT FOR YOUR FRIENDS!")

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = LoggerAgent(path_resolution, command_line_args)
    agent.boot()
