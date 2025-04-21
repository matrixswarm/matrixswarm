# 🧭 UpdateSentinelAgent — AI-powered stale file auditor
# Author: ChatGPT (under orders from General Daniel F. MacDonald)
# ╔════════════════════════════════════════════════════════╗
# ║                    🛡 SENTINEL AGENT 🛡                 ║
# ║     Heartbeat Monitor · Resurrection Watch · Sentinel  ║
# ║   Forged in the signal of Hive Zero | v2.1 Directive   ║
# ║ Accepts: scan / detect / respawn / delay / confirm     ║
# ╚════════════════════════════════════════════════════════╝
import sys
import os
import time
import json
import uuid
from datetime import datetime
if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])

from agent.core.boot_agent import BootAgent

class UpdateSentinelAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.scan_path = "/opt/tasks"  # default directory to scan
        self.age_threshold_days = 90     # default stale threshold
        self.oracle_payload = os.path.join(self.path_resolution["comm_path"], "oracle-1", "payload")
        self.incoming_path = os.path.join(self.path_resolution["comm_path_resolved"], "incoming")
        os.makedirs(self.oracle_payload, exist_ok=True)
        os.makedirs(self.incoming_path, exist_ok=True)

    def post_boot(self):
        self.log("[SENTINEL] UpdateSentinel booted. Monitoring for stale files.")

    def worker(self):
        while self.running:
            for root, _, files in os.walk(self.scan_path):
                for fname in files:
                    full_path = os.path.join(root, fname)
                    age_days = self.get_file_age_days(full_path)
                    if age_days > self.age_threshold_days:
                        self.send_prompt_to_oracle(full_path, age_days)
            self.listen_for_cmds()
            time.sleep(300)  # check every 5 minutes

    def get_file_age_days(self, path):
        last_mod = os.path.getmtime(path)
        return (time.time() - last_mod) / 86400

    def send_prompt_to_oracle(self, filepath, age_days):
        prompt = {
            "file": filepath,
            "last_modified_days": round(age_days, 2),
            "reply_to": self.command_line_args["permanent_id"]
        }
        filename = f"stale_{uuid.uuid4().hex}.prompt"
        with open(os.path.join(self.oracle_payload, filename), "w") as f:
            f.write(json.dumps(prompt, indent=2))
        self.log(f"[SENTINEL] Prompt sent to Oracle for file: {filepath}")

    def listen_for_cmds(self):
        for f in os.listdir(self.incoming_path):
            if f.endswith(".cmd"):
                with open(os.path.join(self.incoming_path, f), "r") as cmd_file:
                    try:
                        cmd = json.load(cmd_file)
                        self.execute_cmd(cmd)
                    except Exception as e:
                        self.log(f"[SENTINEL][ERROR] Failed to parse command: {e}")
                os.remove(os.path.join(self.incoming_path, f))

    def execute_cmd(self, cmd):
        if cmd.get("source") != "oracle":
            self.log(f"[SENTINEL] Rejected command from unknown source: {cmd.get('source')}")
            return

        action = cmd.get("action")
        target = cmd.get("target")

        if action == "archive" and target:
            archive_path = f"/archive/{os.path.basename(target)}"
            try:
                os.rename(target, archive_path)
                self.log(f"[SENTINEL] Archived: {target} → {archive_path}")
            except Exception as e:
                self.log(f"[SENTINEL][ERROR] Archive failed: {e}")
        elif action == "log_only" and target:
            self.log(f"[SENTINEL] Oracle advised review of: {target}")
        else:
            self.log(f"[SENTINEL] Unknown action or malformed command: {action}")

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = UpdateSentinelAgent(path_resolution, command_line_args)
    agent.boot()
