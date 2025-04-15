import os
import shutil
import time
import json

if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])



from agent.core.boot_agent import BootAgent

class ReaperAgent(BootAgent):
    def __init__(self):
        super().__init__(uuid="reaper-executioner")
        self.watch_path = os.path.join(self.path_resolution['comm_path_resolved'], "payload")

    def run(self):
        self.report("ReaperAgent online. Scanning for termination orders...")
        while self.running:
            self.scan_for_orders()
            self.sleep(3)

    def command_listener(self):
        if not os.path.exists(self.watch_path):
            return

        for fname in os.listdir(self.watch_path):
            if not fname.endswith(".json"):
                continue

            path = os.path.join(self.watch_path, fname)
            with open(path, "r") as f:
                try:
                    order = json.load(f)
                except:
                    self.report(f"Failed to parse order: {fname}")
                    continue

            target = order.get("perm_id")
            if not target:
                self.report(f"Missing perm_id in order: {fname}")
                continue

            self.execute_kill(target)
            os.remove(path)

    def execute_kill(self, perm_id):
        pod_path = f"{self.path_resolution['pod_path']}/{perm_id}"
        comm_path = f"{self.path_resolution['comm_path']}/{perm_id}"


        killed = False

        if os.path.exists(pod_path):
            shutil.rmtree(pod_path)
            killed = True

        if os.path.exists(comm_path):
            shutil.rmtree(comm_path)
            killed = True


        status = "terminated" if killed else "not_found"
        self.send_confirmation(perm_id, status)

    def send_confirmation(self, perm_id, status):
        outbox = os.path.join(self.path_resolution['comm_path'], "matrix", "outbox")
        os.makedirs(outbox, exist_ok=True)

        payload = {
            "status": status,
            "perm_id": perm_id,
            "timestamp": time.time(),
            "message": f"{perm_id} {status} by Reaper."
        }

        path = os.path.join(outbox, f"reaper_{perm_id}.json")
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)
        self.report(f"Reaper completed: {perm_id} → {status}")

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = ReaperAgent(path_resolution, command_line_args)
    agent.boot()