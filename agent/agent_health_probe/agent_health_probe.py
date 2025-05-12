# ======== 🛬 LANDING ZONE BEGIN 🛬 ========"
# ======== 🛬 LANDING ZONE END 🛬 ========"
import os
import time
import json
from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    def __init__(self, path_resolution, command_line_args, tree_node):
        super().__init__(path_resolution, command_line_args, tree_node)

        self.target = self.tree_node.get("config", {}).get("target")
        self.interval = self.tree_node.get("config", {}).get("interval", 5)
        self.stream_to = self.tree_node.get("config", {}).get("stream_to", "websocket-relay")

    def worker(self):

        try:
            if not self.target:
                self.log("[HEALTH] No target defined.")
                return  # ✅ replaces illegal 'continue'

            report = self.build_health_report(self.target)
            if report:
                self.dispatch_report(report)
        except Exception as e:
            self.log(f"[HEALTH][ERROR] {e}")

        interruptible_sleep(self, self.interval)

    def build_health_report(self, target_uid):
        report = {
            "target_universal_id": target_uid,
            "source_probe": self.command_line_args["universal_id"],
            "timestamp": time.time(),
            "status": "unknown",
            "last_heartbeat": None,
            "uptime": None,
            "pid": None,
            "spawn_uuid": None
        }

        try:
            comm_root = self.path_resolution["comm_path"]
            pod_root = self.path_resolution["pod_path"]

            # Heartbeat
            ping_file = os.path.join(comm_root, target_uid, "hello.moto", "last.ping")
            if os.path.exists(ping_file):
                delta = time.time() - os.path.getmtime(ping_file)
                report["last_heartbeat"] = round(delta, 2)
                report["status"] = "alive" if delta < 20 else "stale"

            # Spawn record
            spawn_dir = os.path.join(comm_root, target_uid, "spawn")
            if os.path.isdir(spawn_dir):
                files = sorted(os.listdir(spawn_dir), reverse=True)
                for f in files:
                    if f.endswith(".spawn"):
                        with open(os.path.join(spawn_dir, f)) as sf:
                            data = json.load(sf)
                            report["pid"] = data.get("pid")
                            report["spawn_uuid"] = data.get("uuid")
                            if data.get("pid"):
                                try:
                                    import psutil
                                    proc = psutil.Process(data["pid"])
                                    uptime = time.time() - proc.create_time()
                                    report["uptime"] = int(uptime)
                                except Exception:
                                    report["uptime"] = None
                            break

        except Exception as e:
            self.log(f"[HEALTH][BUILD-ERR] {e}")

        return report

    def dispatch_report(self, report):
        inbox = os.path.join(self.path_resolution["comm_path"], self.stream_to, "incoming")
        self.log(f"[HEALTH][DEBUG] Final inbox path: {inbox}")
        if os.path.isdir(inbox):
            fname = f"health_{self.target}_{int(time.time())}.msg"
            packet = {
                "type": "health_report",
                "content": report
            }
            with open(os.path.join(inbox, fname), "w") as f:
                json.dump(packet, f, indent=2)
            self.log(f"[HEALTH] Report sent to {self.stream_to}")
        else:
            # Escalate to Matrix
            matrix_inbox = os.path.join(self.path_resolution["comm_path"], "matrix", "incoming")
            os.makedirs(matrix_inbox, exist_ok=True)
            fname = f"relay_failed_{int(time.time())}.cmd"
            fallback = {
                "type": "relay_failed",
                "timestamp": time.time(),
                "content": {
                    "source": self.command_line_args["universal_id"],
                    "target": self.target,
                    "stream_to": self.stream_to,
                    "report": report
                }
            }
            with open(os.path.join(matrix_inbox, fname), "w") as f:
                json.dump(fallback, f, indent=2)
            self.log(f"[HEALTH] Stream failed → escalated to Matrix.")

    def msg_agent_status_report(self, content, packet):
        new_target = content.get("target_universal_id")
        if new_target:
            self.target = new_target
            self.log(f"[HEALTH] Switched target to: {self.target}")
        else:
            self.log("[HEALTH][ERROR] No target_universal_id in status report msg")


if __name__ == "__main__":
    agent = Agent(path_resolution, command_line_args, tree_node)
    agent.boot()