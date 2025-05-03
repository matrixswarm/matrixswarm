import os
import json
import time
import hashlib
import inotify.adapters
import threading

from agent.core.boot_agent import BootAgent

class FileWatchAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)

        config = tree_node.get("config", {}) if 'tree_node' in globals() else {}
        self.watch_path = config.get("watch_path", "/etc/")
        self.send_to = config.get("send_to", "mailman-1")
        self.agent_id = self.command_line_args.get("universal_id", "filewatch")

        self.target_payload = os.path.join(
            self.path_resolution["comm_path"], self.send_to, "payload"
        )
        os.makedirs(self.target_payload, exist_ok=True)

    def post_boot(self):
        self.log(f"[FILEWATCH] Booted. Watching: {self.watch_path}, Reporting: {self.send_to}")
        threading.Thread(target=self.start_filewatch_loop, daemon=True).start()

    def worker(self):
        pass  # Not used — all work happens in filewatch thread

    def worker_pre(self):
        self.log("[FILEWATCH] Pre-worker setup complete.")

    def worker_post(self):
        self.log("[FILEWATCH] Filewatch loop ended.")

    def start_filewatch_loop(self):
        self.log("[FILEWATCH] Starting inotify watcher loop.")
        try:
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
                    self.log(f"[FILEWATCH][ERROR] {event_type}: {e}")
        except Exception as e:
            self.log(f"[FILEWATCH][FATAL] inotify loop crashed: {e}")

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
            json.dump(entry, f, indent=2)

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = FileWatchAgent(path_resolution, command_line_args)
    agent.boot()
