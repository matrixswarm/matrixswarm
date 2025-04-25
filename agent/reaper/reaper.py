#Authored by Daniel F MacDonald and ChatGPT
# ╔═══════════════════════════════════════════════╗
# ║              ☠ REAPER AGENT ☠                ║
# ║   Tactical Cleanup · Wipe Authority · V2.5    ║
# ║        Forged in the halls of Matrix          ║
# ║  Accepts: .cmd / .json  |  Modes: soft/full   ║
# ╚═══════════════════════════════════════════════╝

# DisposableReaperAgent.py

import os
import json
import time
import shutil
import signal
import psutil

from agent.core.boot_agent import BootAgent
from agent.core.class_lib.processes.reaper import Reaper  # Import Big Reaper
from agent.core.class_lib.file_system.util.json_safe_write import JsonSafeWrite


class DisposableReaperAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.targets = self.command_line_args.get("targets", [])
        self.kill_id = self.command_line_args.get("kill_id", f"reap-{int(time.time())}")
        self.outbox_path = os.path.join(self.path_resolution['comm_path'], "matrix", "outbox")
        os.makedirs(self.outbox_path, exist_ok=True)

    def post_boot(self):
        self.log(f"[DISPOSABLE-REAPER] Mission {self.kill_id} received with targets: {self.targets}")
        threading.Thread(target=self.mission, daemon=True).start()

    def mission(self):
        results = {}
        for perm_id in self.targets:
            success = self.attempt_kill(perm_id)
            results[perm_id] = "terminated" if success else "escalated"

        self.send_mission_report(results)
        self.running = False  # Self-destruct after mission

    def attempt_kill(self, perm_id):
        pod_path = os.path.join(self.path_resolution['pod_path'], perm_id)
        comm_path = os.path.join(self.path_resolution['comm_path'], perm_id)

        # Drop die + tombstone
        incoming = os.path.join(comm_path, "incoming")
        os.makedirs(incoming, exist_ok=True)
        with open(os.path.join(incoming, "die"), "w") as f:
            json.dump({"cmd": "die", "force": False}, f)
        with open(os.path.join(incoming, "tombstone"), "w") as f:
            f.write("true")

        self.log(f"[DISPOSABLE-REAPER] Die and tombstone delivered to {perm_id}")

        # Wait for graceful death
        hello_path = os.path.join(pod_path, "hello.moto")
        max_wait = 18
        elapsed = 0
        while elapsed < max_wait:
            if not os.path.exists(hello_path):
                self.log(f"[DISPOSABLE-REAPER] {perm_id} down gracefully.")
                return True
            time.sleep(3)
            elapsed += 3

        self.log(f"[DISPOSABLE-REAPER] {perm_id} resisted — invoking Big Reaper escalation.")
        self.escalate_with_big_reaper(perm_id)
        return False

    def escalate_with_big_reaper(self, perm_id):
        try:
            big_reaper = Reaper(self.path_resolution['pod_path'], self.path_resolution['comm_path'], timeout_sec=30)
            big_reaper.reap_targets([perm_id])
            self.log(f"[DISPOSABLE-REAPER] Escalation complete for {perm_id}")
        except Exception as e:
            self.log(f"[DISPOSABLE-REAPER] Big Reaper escalation FAILED for {perm_id}: {e}")

    def send_mission_report(self, results):
        payload = {
            "kill_id": self.kill_id,
            "targets": self.targets,
            "results": results,
            "timestamp": time.time(),
            "message": f"Kill operation {self.kill_id} complete."
        }

        report_path = os.path.join(self.outbox_path, f"reaper_mission_{self.kill_id}.json")
        with open(report_path, "w") as f:
            json.dump(payload, f, indent=2)

        self.log(f"[DISPOSABLE-REAPER] Mission report written: {report_path}")


if __name__ == "__main__":

    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = ReaperAgent(path_resolution, command_line_args)
    agent.boot()