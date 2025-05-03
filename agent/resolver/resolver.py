import os
import json
import time
from agent.core.boot_agent import BootAgent
from agent.core.utils.swarm_sleep import interruptible_sleep

class ServiceDirectoryAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.directory = {}

    def worker_pre(self):
        self.log("[RESOLVER] ServiceDirectoryAgent online.")

    def worker(self):
        self.scan_tree_once()
        interruptible_sleep(self, 30)

    def scan_tree_once(self):
        try:
            tree_path = os.path.join(self.path_resolution["comm_path"], "matrix", "agent_tree_master.json")
            if not os.path.exists(tree_path):
                return
            with open(tree_path, "r") as f:
                tree = json.load(f)
            self.directory = {}
            self.parse_tree(tree)
        except Exception as e:
            self.log(f"[RESOLVER][ERROR] {e}")

    def parse_tree(self, node):
        universal_id = node.get("universal_id")
        name = node.get("name")
        app = node.get("app")
        if name:
            if name not in self.directory:
                self.directory[name] = []
            self.directory[name].append({"universal_id": universal_id, "app": app})
        for child in node.get("children", []):
            self.parse_tree(child)

    def process_command(self, command):
        try:
            if command.get("type") == "resolve":
                q = command.get("query", {})
                svc = q.get("service")
                app = q.get("app")
                results = []
                if svc in self.directory:
                    results = [a["universal_id"] for a in self.directory[svc] if not app or a["app"] == app]
                response = {
                    "type": "resolve_response",
                    "results": results,
                    "source": self.command_line_args["universal_id"],
                    "timestamp": time.time()
                }
                self.send_to_matrix(response)
        except Exception as e:
            self.log(f"[RESOLVER][CMD ERROR] {e}")

    def send_to_matrix(self, response):
        path = os.path.join(self.path_resolution["comm_path"], "matrix", "incoming")
        os.makedirs(path, exist_ok=True)
        fname = f"resolve_reply_{int(time.time())}.json"
        with open(os.path.join(path, fname), "w") as f:
            json.dump(response, f, indent=2)

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = ServiceDirectoryAgent(path_resolution, command_line_args)
    agent.boot()
