import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

import time
import json

from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    def __init__(self):
        super().__init__()
        self.name = "AgentDoctor"
        self.max_allowed_beacon_age = 8  # seconds

    def pre_boot(self):
        self.log("[DOCTOR] Swarm-wide diagnostics module armed.")

    def post_boot(self):
        self.log("[DOCTOR] Monitoring active threads via intelligent beacon protocol.")
        self.log("[IDENTITY] Registering with Matrix...")
        #self.dispatch_identity_command()

    def is_phantom(self, agent_id):
        pod_root = self.path_resolution["pod_path"]
        for pod_id in os.listdir(pod_root):
            boot_file = os.path.join(pod_root, pod_id, "boot.json")
            try:
                with open(boot_file) as f:
                    boot_data = json.load(f)
                    if boot_data.get("universal_id") == agent_id:
                        return False
            except:
                continue
        return True

    def read_poke_file(self, path):
        try:
            with open(path, "r") as f:
                raw = f.read().strip()
                if raw.startswith("{"):
                    return json.loads(raw)
                else:
                    return {"status": "alive", "last_seen": float(raw)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def verify_agent_consciousness(self, agent_id, threads=("heartbeat","worker", "packet_listener")):
        comm_path = os.path.join(self.path_resolution["comm_path"], agent_id)
        beacon_dir = os.path.join(comm_path, "hello.moto")

        now = time.time()
        status_report = {}

        if not os.path.isdir(beacon_dir):
            self.log(f"[DOCTOR] Missing hello.moto folder for {agent_id}")
            for thread in threads:
                status_report[thread] = "❌ no beacon (no hello.moto)"
            return status_report

        for thread in threads:
            poke_file = os.path.join(beacon_dir, f"poke.{thread}")
            if not os.path.exists(poke_file):
                status_report[thread] = "❌ no beacon"
                continue

            beacon = self.read_poke_file(poke_file)
            status = beacon.get("status", "unknown")
            timeout = beacon.get("timeout", self.max_allowed_beacon_age)

            if status == "alive":
                age = round(now - beacon.get("last_seen", 0), 2)
                if age > timeout * 2:
                    status_report[thread] = f"💥 reflex expired ({age}s > {timeout}s)"
                elif age > timeout:
                    status_report[thread] = f"⚠️ stale ({age}s)"
                else:
                    status_report[thread] = f"✅ {age}s"
            elif status == "dead":
                err = beacon.get("error", "no error provided")
                status_report[thread] = f"💀 dead: {err}"
            elif status == "unused":
                status_report[thread] = f"🟦 unused"
            else:
                status_report[thread] = f"❓ unknown status"

        return status_report

    def worker(self, config:dict = None):
        self.log("[DOCTOR] Beginning swarm scan...")
        agents = self.get_agents_list()

        for agent_id in agents:
            if agent_id == self.command_line_args.get("universal_id"):
                continue

            if self.is_phantom(agent_id):
                self.log(f"🩺 {agent_id}\n  • 👻 phantom agent — comm exists, no pod detected")
                continue

            status = self.verify_agent_consciousness(agent_id)
            log_lines = [f"🩺 {agent_id}"]
            for thread, stat in status.items():
                log_lines.append(f"  • {thread:<16} {stat}")
            self.log("\n".join(log_lines))

        interruptible_sleep(self, 30)

    def get_agents_list(self):
        comm_path = self.path_resolution.get("comm_path", "/matrix/ai/latest/comm")
        agents = []
        for agent_id in os.listdir(comm_path):
            base = os.path.join(comm_path, agent_id)
            if not os.path.isdir(base):
                continue
            if os.path.isdir(os.path.join(base, "incoming")) or os.path.isdir(os.path.join(base, "hello.moto")):
                agents.append(agent_id)
        return agents


if __name__ == "__main__":
    agent = Agent()
    agent.boot()