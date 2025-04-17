# Matrix: An AI OS System
# Copyright (c) 2025 Daniel MacDonald
# Licensed under the MIT License. See LICENSE file in project root for details.
import sys
import os
import time
import json

if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])


from agent.core.boot_agent import BootAgent

class CommanderAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.orbits = {}

    def pre_boot(self):
        self.log("[COMMANDER] Pre-boot check passed.")

    def post_boot(self):
        self.log("[COMMANDER] Active swarm dashboard engaged.")

    def worker(self):
        while self.running:
            self.track_agents()
            time.sleep(10)

    def track_agents(self):
        comm_root = self.path_resolution["comm_path"]
        flat = []
        for agent_id in os.listdir(comm_root):
            hello_path = os.path.join(comm_root, agent_id, "hello.moto")
            if not os.path.isdir(hello_path):
                if agent_id == self.command_line_args.get("permanent_id"):
                    continue

            try:
                latest = max((os.path.getmtime(os.path.join(hello_path, f)) for f in os.listdir(hello_path)), default=0)
                delta = time.time() - latest
                status = "✅" if delta < 20 else "⚠️"
                flat.append((agent_id, round(delta, 1), status))
            except:
                flat.append((agent_id, "ERR", "❌"))

        self.render_table(flat)

    def render_table(self, flat):
        flat.sort(key=lambda x: x[0])
        self.log("\n[COMMANDER] Swarm Agent Status:")
        for agent_id, age, flag in flat:
            self.log(f"   {flag} {agent_id.ljust(28)}  last seen: {age}s ago")

    def process_command(self, command):
        action = command.get("action")
        if action == "resurrect":
            target = command.get("target")
            if target:
                self.send_resurrect(target)
        else:
            self.log(f"[COMMANDER] Unknown command: {command}")

    def send_resurrect(self, agent_id):
        matrix_comm = os.path.join(self.path_resolution["comm_path"], "matrix", "incoming")
        os.makedirs(matrix_comm, exist_ok=True)
        payload = {
            "action": "request_delegation",
            "requester": agent_id
        }
        ts = int(time.time())
        filename = f"resurrect_{agent_id}_{ts}.cmd"
        with open(os.path.join(matrix_comm, filename), "w") as f:
            json.dump(payload, f, indent=2)
        self.log(f"[COMMANDER] Resurrection request for {agent_id} dispatched to Matrix → {filename}")


if __name__ == "__main__":
    # label = None
    # if "--label" in sys.argv:
    #   label = sys.argv[sys.argv.index("--label") + 1]

    pid = os.getpid()

    # current directory of the agent script or it wont be able to find itself
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))

    agent = CommanderAgent(path_resolution, command_line_args)

    agent.boot()
