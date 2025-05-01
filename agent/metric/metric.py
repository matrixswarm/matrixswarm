import os
import time
import json
import hashlib
import psutil
import shutil

from agent.core.boot_agent import BootAgent

class MetricsAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)

        self.report_to = tree_node.get("config", {}).get("report_to", "mailman-1")
        self.ask_oracle = tree_node.get("config", {}).get("oracle", "oracle-1")
        self.interval = tree_node.get("config", {}).get("interval_sec", 10)

        self.outbox = os.path.join(self.path_resolution["comm_path"], self.report_to, "payload")
        self.oracle_payload = os.path.join(self.path_resolution["comm_path"], self.ask_oracle, "payload")

        os.makedirs(self.outbox, exist_ok=True)
        os.makedirs(self.oracle_payload, exist_ok=True)

        self.history = []

    def get_metrics(self):
        cpu = os.getloadavg()[0]
        ram = psutil.virtual_memory().percent
        disk = shutil.disk_usage("/").free / (1024 ** 3)
        with open("/proc/uptime", "r") as f:
            uptime = float(f.readline().split()[0])
        return {
            "cpu": round(cpu, 2),
            "ram_used_percent": round(ram, 2),
            "disk_free_gb": round(disk, 2),
            "uptime_sec": int(uptime)
        }

    def log_metrics(self, data):
        payload = {
            "uuid": self.command_line_args["permanent_id"],
            "timestamp": time.time(),
            "severity": "info",
            "msg": f"CPU: {data['cpu']}, RAM: {data['ram_used_percent']}%, Disk Free: {data['disk_free_gb']} GB, Uptime: {data['uptime_sec']} sec"
        }
        hashval = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
        fname = f"{int(time.time())}_{hashval}.json"
        with open(os.path.join(self.outbox, fname), "w") as f:
            json.dump(payload, f)

    def query_oracle(self, summary):
        query = {
            "source": self.command_line_args["permanent_id"],
            "query_type": "trend_analysis",
            "timestamp": time.time(),
            "payload": summary
        }
        fname = f"metrics_trend_query_{int(time.time())}.json"
        with open(os.path.join(self.oracle_payload, fname), "w") as f:
            json.dump(query, f)
        self.log("[METRICS] Oracle query dispatched.")

    def worker(self):

        data = self.get_metrics()
        self.log_metrics(data)
        self.history.append(data)

        if len(self.history) >= 5:
            summary = {
                "cpu_avg": round(sum(d["cpu"] for d in self.history[-5:]) / 5, 2),
                "ram_avg": round(sum(d["ram_used_percent"] for d in self.history[-5:]) / 5, 2),
                "disk_min": round(min(d["disk_free_gb"] for d in self.history[-5:]), 2),
                "uptime": self.history[-1]["uptime_sec"]
            }
            self.query_oracle(summary)

        time.sleep(self.interval)

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = MetricsAgent(path_resolution, command_line_args)
    agent.boot()
