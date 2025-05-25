# 🧭 UpdateSentinelAgent — AI-powered stale file auditor
# Author: ChatGPT (under orders from General Daniel F. MacDonald)
# ╔════════════════════════════════════════════════════════╗
# ║               🛡 FILE SENTINEL AGENT 🛡                 ║
# ║     Heartbeat Monitor · Resurrection Watch · Sentinel  ║
# ║   Forged in the signal of Hive Zero | v2.1 Directive   ║
# ║ Accepts: scan / detect / respawn / delay / confirm     ║
# ╚════════════════════════════════════════════════════════╝
import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))
import time
import json
import uuid
from datetime import datetime

from core.utils.swarm_sleep import interruptible_sleep
from core.boot_agent import BootAgent

class Agent(BootAgent):
    def __init__(self):
        super().__init__()
        config = self.command_line_args.get("config", {})
        self.scan_path = config.get("scan_path", "/tmp")
        self.age_threshold_days = config.get("age_threshold_days", 90)
        self.oracle_payload = os.path.join(self.path_resolution["comm_path"], "oracle-1", "payload")
        self.incoming_path = os.path.join(self.path_resolution["comm_path_resolved"], "incoming")
        os.makedirs(self.oracle_payload, exist_ok=True)
        os.makedirs(self.incoming_path, exist_ok=True)

    def worker_pre(self):
        self.log(f"[SENTINEL] UpdateSentinel initialized. Monitoring {self.scan_path}.")

    def worker(self):
        self.scan_files_once()
        self.check_oracle_cmds_once()
        interruptible_sleep(self, 300)

    def worker_post(self):
        self.log("[SENTINEL] Sentinel agent is shutting down.")

    def scan_files_once(self):
        try:
            for root, _, files in os.walk(self.scan_path):
                for fname in files:
                    full_path = os.path.join(root, fname)
                    age_days = self.get_file_age_days(full_path)
                    if age_days > self.age_threshold_days:
                        self.send_prompt_to_oracle(full_path, age_days)
        except Exception as e:
            self.log(f"[SENTINEL][SCAN ERROR] {e}")

    def check_oracle_cmds_once(self):
        for f in os.listdir(self.incoming_path):
            if f.endswith(".cmd"):
                try:
                    with open(os.path.join(self.incoming_path, f), "r") as cmd_file:
                        cmd = json.load(cmd_file)
                        self.execute_cmd(cmd)
                except Exception as e:
                    self.log(f"[SENTINEL][CMD ERROR] {e}")
                os.remove(os.path.join(self.incoming_path, f))

    def get_file_age_days(self, path):
        last_mod = os.path.getmtime(path)
        return (time.time() - last_mod) / 86400

    def send_prompt_to_oracle(self, filepath, age_days):
        prompt = {
            "file": filepath,
            "last_modified_days": round(age_days, 2),
            "reply_to": self.command_line_args["universal_id"]
        }
        filename = f"stale_{uuid.uuid4().hex}.prompt"
        with open(os.path.join(self.oracle_payload, filename), "w") as f:
            f.write(json.dumps(prompt, indent=2))
        self.log(f"[SENTINEL] Prompt sent to Oracle for: {filepath}")

    def forward_to_mailman(self, entry):
        try:
            file = f"sentinel_log_{uuid.uuid4().hex}.msg"
            path = os.path.join(self.path_resolution["comm_path"], "mailman-1", "incoming", file)
            with open(path, "w") as f:
                f.write(json.dumps(entry, indent=2))
        except Exception as e:
            self.log(f"[SENTINEL][MAILMAN ERROR] {e}")

    def execute_cmd(self, cmd):
        log_entry = {
            "source": self.command_line_args.get("universal_id", "update-sentinel"),
            "type": "action",
            "event": cmd.get("action"),
            "target": cmd.get("target"),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
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
                self.forward_to_mailman(log_entry)
            except Exception as e:
                self.log(f"[SENTINEL][ARCHIVE ERROR] {e}")
        elif action == "log_only" and target:
            self.log(f"[SENTINEL] Oracle flagged for review: {target}")
            self.forward_to_mailman(log_entry)
        else:
            self.log(f"[SENTINEL] Unknown or malformed action: {action}")

if __name__ == "__main__":
    agent = Agent()
    agent.boot()