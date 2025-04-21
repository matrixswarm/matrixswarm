# 🧹 SweepCommanderAgent — Autonomous Execution Unit
# Author: ChatGPT (under orders from General Daniel F. MacDonald)
# Description: Sends prompts to OracleAgent, receives .cmd replies, and executes validated actions
import os
import sys
import time
import json
import uuid

if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])

from agent.core.boot_agent import BootAgent


class SweepCommanderAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.oracle_payload = os.path.join(self.path_resolution["comm_path"], "oracle-1", "payload")
        self.incoming_path = os.path.join(self.path_resolution["comm_path_resolved"], "incoming")
        os.makedirs(self.oracle_payload, exist_ok=True)
        os.makedirs(self.incoming_path, exist_ok=True)

    def post_boot(self):
        self.log("[SWEEP] SweepCommander ready. Sending prompt to Oracle.")
        self.send_prompt_to_oracle()

    def worker(self):
        self.log("[SWEEP] SweepCommander is watching for Oracle commands.")
        while self.running:
            for f in os.listdir(self.incoming_path):
                if f.endswith(".cmd"):
                    cmd_path = os.path.join(self.incoming_path, f)
                    with open(cmd_path, "r") as f:
                        try:
                            cmd = json.load(f)
                            self.handle_command(cmd)
                        except Exception as e:
                            self.log(f"[SWEEP][ERROR] Failed to parse command: {e}")
                    os.remove(cmd_path)
            time.sleep(3)

    def send_prompt_to_oracle(self):
        prompt_data = {
            "system_state": {
                "dead_pods": self.count_dead_pods(),
                "active_uuid": self.command_line_args["install_name"]
            },
            "reply_to": self.command_line_args["permanent_id"]
        }
        fname = f"sweep_{uuid.uuid4().hex}.prompt"
        with open(os.path.join(self.oracle_payload, fname), "w") as f:
            f.write(json.dumps(prompt_data, indent=2))
        self.log(f"[SWEEP] Prompt sent to Oracle: {fname}")

    def count_dead_pods(self):
        pod_root = self.path_resolution.get("pod_path", "/pod")
        return len([d for d in os.listdir(pod_root) if d.startswith("dead")])

    def handle_command(self, cmd):
        source = cmd.get("source")
        if source != "oracle":
            self.log(f"[SWEEP] Ignoring command from unknown source: {source}")
            return

        action = cmd.get("action")
        target = cmd.get("target")

        if action == "purge_folder" and target:
            try:
                if os.path.exists(target):
                    for file in os.listdir(target):
                        fpath = os.path.join(target, file)
                        os.remove(fpath) if os.path.isfile(fpath) else None
                    self.log(f"[SWEEP] Purged folder: {target}")
            except Exception as e:
                self.log(f"[SWEEP][ERROR] Failed to purge folder {target}: {e}")
        else:
            self.log(f"[SWEEP] Unknown or missing action: {action}")

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    sweep = SweepCommanderAgent(path_resolution, command_line_args)
    sweep.boot()
