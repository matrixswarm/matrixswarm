import os
import json
import time
import hashlib
import requests

from agent.core.boot_agent import BootAgent

class UptimePingerAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)

        config = tree_node.get("config", {})
        self.targets = config.get("targets", ["https://example.com"])
        self.interval = config.get("interval_sec", 30)
        self.alert_to = config.get("alert_to", "mailman-1")
        self.payload_out = os.path.join(self.path_resolution["comm_path"], self.alert_to, "payload")
        os.makedirs(self.payload_out, exist_ok=True)

    def post_boot(self):
        self.log(f"[PINGER] Monitoring targets every {self.interval}s: {self.targets}")

    def send_log(self, target, status_code, response_time, success):
        msg = f"{'UP' if success else 'DOWN'}: {target} [{status_code}] in {response_time:.2f}s" if success else f"DOWN: {target} [{status_code}]"
        payload = {
            "uuid": self.command_line_args["permanent_id"],
            "timestamp": time.time(),
            "severity": "info" if success else "error",
            "msg": msg
        }
        hashval = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
        filename = f"{int(time.time())}_{hashval}.json"
        with open(os.path.join(self.payload_out, filename), "w") as f:
            json.dump(payload, f)

    def worker(self):
        while self.running:
            for url in self.targets:
                try:
                    start = time.time()
                    r = requests.get(url, timeout=5)
                    elapsed = time.time() - start
                    self.send_log(url, r.status_code, elapsed, r.ok)
                except Exception as e:
                    self.send_log(url, "ERR", 0, False)
            time.sleep(self.interval)

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = UptimePingerAgent(path_resolution, command_line_args)
    agent.boot()