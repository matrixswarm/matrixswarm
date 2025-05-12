
# ======== 🛬 LANDING ZONE BEGIN 🛬 ========"
# ======== 🛬 LANDING ZONE END 🛬 ========"

import os
import json
import time
from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    def __init__(self, path_resolution, command_line_args, tree_node):
        super().__init__(path_resolution, command_line_args, tree_node)

    def worker_pre(self):
        self.log("[LOGGER] Booted and ready for timestamp duty.")

    def worker(self):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        self.log(f"[LOGGER] Log cycle at {now}")
        interruptible_sleep(self, 10)

    def worker_post(self):
        self.log("[LOGGER] LoggerAgent is shutting down.")

    def process_command(self, command):
        action = command.get("action")
        if action == "log_message":
            msg = command.get("message", "(no message)")
            self.log(f"[COMMAND-LOG] {msg}")
        elif action == "die":
            self.log("[COMMAND] Received die command.")
            self.running = False
        elif action == "update_delegates":
            self.log("[COMMAND] Delegate update received. Saving tree and spawning.")
            tree_path = os.path.join(
                self.path_resolution["comm_path"],
                self.command_line_args["universal_id"],
                "agent_tree.json"
            )
            with open(tree_path, "w") as f:
                json.dump(command["tree_snapshot"], f, indent=2)
            self.spawn_manager()

        self.log(f"[COMMAND] Received command: {command}")

if __name__ == "__main__":
    agent = Agent(path_resolution, command_line_args, tree_node)
    agent.boot()
