import os
import json
import sys
import time
import threading
import hashlib
from datetime import datetime
import inotify.adapters

if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])

from agent.core.boot_agent import BootAgent



class FileWatchAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)

        # Path to watch — from tree_node, fallback default
        self.watch_path = tree_node.get("config", {}).get("watch_path", "/etc/")
        self.send_to = tree_node.get("config", {}).get("send_to", "mailman-1")
        self.agent_id = self.command_line_args.get("permanent_id", "filewatch")

        # Drop to this target's payload
        self.target_payload = os.path.join(
            self.path_resolution["comm_path"], self.send_to, "payload"
        )
        os.makedirs(self.target_payload, exist_ok=True)

    def post_boot(self):
        self.log(f"[FILEWATCH] Watching {self.watch_path}, reporting to {self.send_to}")

    def log_event(self, event, filepath):
        entry = {
            "uuid": self.agent_id,
            "timestamp": time.time(),
            "severity": "info",
            "msg": f"{event}: {filepath}"
        }
        hashval = hashlib.sha256(json.dumps(entry).encode()).hexdigest()
        outpath = os.path.join(self.target_payload, f"{int(time.time())}_{hashval}.json")
        with open(outpath, "w") as f:
            json.dump(entry, f)

    def worker(self):
        self.log("[FILEWATCH] Worker engaged.")
        i = inotify.adapters.InotifyTree(self.watch_path)

        for event in i.event_gen(yield_nones=False):
            if not self.running:
                break

            (_, type_names, path, filename) = event
            event_type = ",".join(type_names)
            full_path = os.path.join(path, filename)

            try:
                self.log_event(event_type, full_path)
                self.log(f"[FILEWATCH] {event_type}: {full_path}")
            except Exception as e:
                self.log(f"[FILEWATCH][ERROR] Failed to log event {event_type}: {e}")

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = FileWatchAgent(path_resolution, command_line_args)
    agent.boot()
