import time
import json
import sys
import os

if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])

from agent.core.class_lib.time_utils.heartbeat_checker import last_heartbeat_delta
from agent.core.mixin.delegation import DelegationMixin
from agent.core.boot_agent import BootAgent

class Watchdog2Agent(BootAgent, DelegationMixin):

    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.orbits = {}
        self.pending_resurrections = {}
        self.label = self.command_line_args.get("permanent_id", "UNKNOWN").upper()

    def pre_boot(self):
        self.log("[WATCHDOG-2] Pre-boot check passed.")

    def post_boot(self):
        self.log("[WATCHDOG-2] Boot complete. Resurrection monitor engaged.")

    def worker(self):
        self.log("[WATCHDOG-2] Resurrection scan underway...")
        while self.running:
            self.check_heartbeats()
            self.retry_failed_agents()
            time.sleep(5)

    def check_heartbeats(self):
        comm_path = self.path_resolution["comm_path"]
        now = time.time()
        timeout = 20

        for agent_id in os.listdir(comm_path):
            if agent_id in self.pending_resurrections:
                continue

            delta = last_heartbeat_delta(comm_path, agent_id)
            if delta is None:
                continue

            if delta > timeout:
                self.log(f"[{self.label}] {agent_id} missed heartbeat. Starting recovery attempts.")
                self.pending_resurrections[agent_id] = {"attempts": 1, "last_seen": now}
                self.recover_agent(agent_id)
            else:
                self.log(f"[{self.label}] {agent_id} heartbeat OK ({int(delta)}s ago)")

    def retry_failed_agents(self):
        now = time.time()
        for agent_id, info in list(self.pending_resurrections.items()):
            if self.confirm_resurrection(agent_id):
                self.log(f"[WATCHDOG-2] Resurrection confirmed for {agent_id}.")
                del self.pending_resurrections[agent_id]
            else:
                if info["attempts"] >= 3:
                    self.log(f"[WATCHDOG-2] {agent_id} failed to resurrect after 3 tries. Marked as fallen.")
                    del self.pending_resurrections[agent_id]
                elif now - info["last_seen"] > 20:
                    info["attempts"] += 1
                    info["last_seen"] = now
                    self.log(f"[WATCHDOG-2] Retrying resurrection for {agent_id} (attempt {info['attempts']}).")
                    self.recover_agent(agent_id)

    def confirm_resurrection(self, agent_id):
        hello_path = os.path.join(self.path_resolution["comm_path"], agent_id, "hello.moto")
        if not os.path.isdir(hello_path):
            return False
        try:
            latest = max((os.path.getmtime(os.path.join(hello_path, f)) for f in os.listdir(hello_path)), default=0)
            return (time.time() - latest) < 15
        except:
            return False

    def recover_agent(self, perm_id):
        matrix_comm = os.path.join(self.path_resolution["comm_path"], "matrix", "incoming")
        os.makedirs(matrix_comm, exist_ok=True)

        request = {
            "action": "request_delegation",
            "requester": perm_id
        }

        filename = f"request_delegation_{int(time.time())}.cmd"
        full_path = os.path.join(matrix_comm, filename)

        with open(full_path, "w") as f:
            json.dump(request, f, indent=2)

        self.log(f"[WATCHDOG-2] Recovery request dispatched to Matrix for {perm_id} → {filename}")

    def process_command(self, command):
        try:
            action = command.get("action")
            if action == "die":
                self.log("[COMMAND] Watchdog-2 received die command.")
                self.running = False
            elif action == "update_delegates":
                self.process_update_delegates(command)  # From DelegationMixin
            else:
                self.log(f"[COMMAND] Ignoring unknown action: {action}")
        except Exception as e:
            self.log(f"[CMD-ERROR] {e}")


if __name__ == "__main__":

    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = Watchdog2Agent(path_resolution, command_line_args)
    agent.boot()