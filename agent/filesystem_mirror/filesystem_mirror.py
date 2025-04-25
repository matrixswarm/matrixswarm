import os
import time
import json

from agent.core.boot_agent import BootAgent

class FilesystemMirrorAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        config = tree_node.get("config", {})

        self.watch_path = config.get("watch_path", "/etc")
        self.mode = config.get("mode", "once")  # or "cycle"
        self.self_destruct = config.get("self_destruct", False)

        self.report_to = config.get("report_to", "mailman-1")
        self.out_dir = os.path.join(self.path_resolution["comm_path"], self.report_to, "payload")
        os.makedirs(self.out_dir, exist_ok=True)

    def worker(self):
        self.log(f"[MIRROR] Scanning: {self.watch_path} [mode: {self.mode}]")

        self.scan_and_log()

        if self.self_destruct:
            self.log("[MIRROR] Mission complete. Self-destruct initiated.")
            self.running = False
            return

        while self.running and self.mode == "cycle":
            time.sleep(10)
            self.scan_and_log()

    def scan_and_log(self):
        snapshot = []

        try:
            for root, dirs, files in os.walk(self.watch_path):
                for fname in files:
                    try:
                        path = os.path.join(root, fname)
                        stat = os.stat(path)
                        snapshot.append({
                            "file": path,
                            "size": stat.st_size,
                            "mtime": stat.st_mtime
                        })
                    except Exception:
                        continue
        except Exception as e:
            self.log(f"[MIRROR][ERROR] Failed to scan {self.watch_path}: {e}")
            return

        payload = {
            "uuid": self.command_line_args["permanent_id"],
            "timestamp": time.time(),
            "watch_path": self.watch_path,
            "file_count": len(snapshot),
            "files": snapshot[:50]  # Limit for brevity
        }

        fname = f"mirror_{int(time.time())}.json"
        with open(os.path.join(self.out_dir, fname), "w") as f:
            json.dump(payload, f, indent=2)

        self.log(f"[MIRROR] Snapshot complete. {len(snapshot)} files logged.")

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    filesystem_mirror = FilesystemMirrorAgent(path_resolution, command_line_args)
    filesystem_mirror.boot()
