#Authored by Daniel F MacDonald and ChatGPT
# ╔════════════════════════════════════════════════════════╗
# ║               🧹 SCAVENGER AGENT 🧹                    ║
# ║   Runtime Sweeper · Pod Watchdog · Tombstone Handler   ║
# ║   Brought online under blackout protocol | Rev 1.8      ║
# ║   Monitors: /pod/* | Deletes: expired / orphaned nodes ║
# ╚════════════════════════════════════════════════════════╝
import os
import time
import json
import shutil

from agent.core.class_lib.file_system.util.json_safe_write import JsonSafeWrite
from agent.core.boot_agent import BootAgent



class ScavengerAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.watch_path = os.path.join(self.path_resolution['comm_path'], self.command_line_args['permanent_id'], "payload")
        os.makedirs(self.watch_path, exist_ok=True)

    def command_listener(self):
        self.log("ScavengerAgent online. Watching for kill commands...")
        while self.running:
            if not os.path.exists(self.watch_path):
                time.sleep(2)
                continue

            for fname in os.listdir(self.watch_path):
                if not fname.endswith(".cmd"):
                    continue

                perm_id = fname.replace("scavenge_", "").replace("kill_", "").replace(".cmd", "")
                full_path = os.path.join(self.watch_path, fname)
                self.execute_stop(perm_id, annihilate="scavenge" in fname)
                os.remove(full_path)

            time.sleep(2)

    def execute_stop(self, perm_id, annihilate=True):
        comm_path = os.path.join(self.path_resolution['comm_path'], perm_id)
        die_path = os.path.join(comm_path, "incoming", "die")

        # Step 1: Ask it to die nicely
        JsonSafeWrite.safe_write(die_path, "terminate")
        self.log(f"[SCAVENGER] Sent die signal to {perm_id}")

        # Step 2: Do not remove pod or comm — just issue the pause
        status = "pause_requested"
        self.send_confirmation(perm_id, status)
        self.notify_matrix_to_verify(perm_id)

    def execute_kill(self, perm_id):
        pod_path = os.path.join(self.path_resolution['pod_path'], perm_id)
        comm_path = os.path.join(self.path_resolution['comm_path'], perm_id)
        killed = False

        if os.path.exists(pod_path):
            shutil.rmtree(pod_path)
            killed = True

        if os.path.exists(comm_path):
            shutil.rmtree(comm_path)
            killed = True

        self.log(f"[SCAVENGER] {perm_id} has been fully annihilated")
        status = "terminated" if killed else "not_found"
        self.send_confirmation(perm_id, status)
        self.notify_matrix_to_verify(perm_id)

    def send_confirmation(self, perm_id, status):
        outbox = os.path.join(self.path_resolution['comm_path'], "matrix", "outbox")
        os.makedirs(outbox, exist_ok=True)

        payload = {
            "status": status,
            "perm_id": perm_id,
            "timestamp": time.time(),
            "message": f"{perm_id} {status} by Scavenger."
        }

        fpath = os.path.join(outbox, f"reaper_{perm_id}.json")
        with open(fpath, "w") as f:
            json.dump(payload, f, indent=2)
        self.log(f"[SCAVENGER] Completed: {perm_id} → {status}")

    def notify_matrix_to_verify(self, perm_id):
        verify_path = os.path.join(self.path_resolution['comm_path'], "matrix", "outbox", f"verify_{perm_id}.json")
        payload = {
            "type": "verify_branch",
            "perm_id": perm_id,
            "origin": self.command_line_args.get("permanent_id", "unknown"),
            "timestamp": time.time(),
            "status": "post_kill"
        }
        with open(verify_path, "w") as f:
            json.dump(payload, f, indent=2)
        self.log(f"[SCAVENGER] Verification request issued for: {perm_id}")



if __name__ == "__main__":

    # current directory of the agent script or it wont be able to find itself
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))

    agent = ScavengerAgent(path_resolution, command_line_args)
    agent.boot()
