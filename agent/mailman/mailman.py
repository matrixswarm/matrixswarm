# ╔════════════════════════════════════════════════════════╗
# ║                📬 MAILMAN AGENT                        ║
# ║  System Logger · Tally Tracker · Message Forwarder     ║
# ║  Spawned from Matrix | No excuses. Just receipts.      ║
# ╚════════════════════════════════════════════════════════╝

import os
import json
import time
import hashlib
import sys
import threading
from datetime import datetime

if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])

from agent.core.boot_agent import BootAgent

class MailmanAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.payload_dir = os.path.join(self.path_resolution["comm_path_resolved"], "payload")
        self.mail_dir = os.path.join(self.path_resolution["comm_path_resolved"], "mail")
        self.tally_dir = os.path.join(self.path_resolution["comm_path_resolved"], "tally")
        self.incoming_dir = os.path.join(self.path_resolution["comm_path_resolved"], "incoming")
        os.makedirs(self.payload_dir, exist_ok=True)
        os.makedirs(self.mail_dir, exist_ok=True)
        os.makedirs(self.tally_dir, exist_ok=True)
        os.makedirs(self.incoming_dir, exist_ok=True)
        self.hash_cache = set()

    def post_boot(self):
        self.log("[MAILMAN] MailmanAgent v2.1 operational. Watching payload inbox.")

    def hash_msg(self, content):
        return hashlib.sha256(content.encode()).hexdigest()

    def write_mail_file(self, hashval, content):
        path = os.path.join(self.mail_dir, f"{hashval}.json")
        with open(path, "w") as f:
            f.write(content)

    def write_tally_file(self, hashval, content):
        try:
            data = json.loads(content)
            entry = {
                "uuid": data.get("uuid", "unknown"),
                "timestamp": data.get("timestamp", time.time()),
                "severity": data.get("severity", "info")
            }
            path = os.path.join(self.tally_dir, f"{hashval}.msg")
            with open(path, "w") as f:
                json.dump(entry, f)
        except Exception as e:
            self.log(f"[MAILMAN][TALLY-ERROR] {e}")

    def forward_to_incoming(self, hashval, content):
        try:
            path = os.path.join(self.incoming_dir, f"{int(time.time())}_{hashval}.msg")
            with open(path, "w") as f:
                f.write(content)
        except Exception as e:
            self.log(f"[MAILMAN][FORWARD-ERROR] {e}")

    def worker(self):
        self.log("[MAILMAN] Worker thread active.")
        while self.running:
            try:
                files = sorted(os.listdir(self.payload_dir))
                for file in files:
                    if not file.endswith(".json"):
                        continue
                    fullpath = os.path.join(self.payload_dir, file)
                    try:
                        content = open(fullpath).read()
                        hashval = self.hash_msg(content)
                        if hashval in self.hash_cache:
                            os.remove(fullpath)
                            continue
                        self.hash_cache.add(hashval)
                        self.write_mail_file(hashval, content)
                        self.write_tally_file(hashval, content)
                        self.forward_to_incoming(hashval, content)
                        self.log(f"[MAILMAN] Logged: {file}")
                        os.remove(fullpath)
                    except Exception as e:
                        self.log(f"[MAILMAN][ERROR] Failed to process {file}: {e}")
            except Exception as loop_error:
                self.log(f"[MAILMAN][LOOP-ERROR] {loop_error}")
            time.sleep(1)

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = MailmanAgent(path_resolution, command_line_args)
    agent.boot()
