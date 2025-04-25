#Authored by Daniel F MacDonald and ChatGPT
# ╔═══════════════════════════════════════════════╗
# ║              ☠ REAPER AGENT ☠                ║
# ║   Tactical Cleanup · Wipe Authority · V2.5    ║
# ║        Forged in the halls of Matrix          ║
# ║  Accepts: .cmd / .json  |  Modes: soft/full   ║
# ╚═══════════════════════════════════════════════╝

import os
import time
import json
import shutil

from agent.core.boot_agent import BootAgent
from agent.core.class_lib.file_system.util.json_safe_write import JsonSafeWrite

class ReaperAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):

        super().__init__(path_resolution, command_line_args)

        self.watch_path = os.path.join(self.path_resolution['comm_path'], self.command_line_args["permanent_id"], "payload")

        os.makedirs(self.watch_path, exist_ok=True)


    def command_listener(self):
        self.log("ReaperAgent online. Scanning for termination orders...")
        while self.running:
            if not os.path.exists(self.watch_path):
                time.sleep(4)
                continue

            for fname in os.listdir(self.watch_path):

                if fname.endswith(".cmd") or fname.endswith(".json"):
                    continue

                path = os.path.join(self.watch_path, fname)

                if fname.endswith(".json"):
                    with open(path, "r") as f:
                        try:
                            order = json.load(f)
                            target = order.get("perm_id")
                            annihilate = order.get("annihilate", True)
                        except:
                            self.log(f"Failed to parse JSON kill order: {fname}")
                            continue
                else:  # .cmd file
                    target = fname.replace("scavenge_", "").replace(".cmd", "")
                    annihilate = True  # default .cmd to full wipe

                if not target:
                    self.log(f"Missing perm_id in order: {fname}")
                    continue

                self.execute_kill(target, annihilate=annihilate)
                os.remove(path)

            time.sleep(4)

    def execute_kill(self, perm_id, annihilate=True):
        pod_path = f"{self.path_resolution['pod_path']}/{perm_id}"
        comm_path = f"{self.path_resolution['comm_path']}/{perm_id}"
        killed = False

        if annihilate:
            # Stage soft kill first
            die_cmd = os.path.join(comm_path, "payload", "die.cmd")
            JsonSafeWrite.safe_write(die_cmd, "terminate")
            self.log(f"[REAPER] Annihilation requested — issued die.cmd to {perm_id}")

            # Wait for hello.moto shutdown signal
            hello_path = os.path.join(pod_path, "hello.moto")
            for _ in range(6):  # wait up to 18 seconds
                if not os.path.exists(hello_path):
                    break
                time.sleep(3)

            # Begin purge
            if os.path.exists(pod_path):
                shutil.rmtree(pod_path)
                killed = True
            if os.path.exists(comm_path):
                shutil.rmtree(comm_path)
                killed = True

            status = "terminated" if killed else "not_found"
        else:
            # Soft kill = pod wipe only
            if os.path.exists(pod_path):
                shutil.rmtree(pod_path)
                killed = True
            status = "soft_killed" if killed else "not_found"

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
        self.log(f"[REAPER] Completed: {perm_id} → {status}")




if __name__ == "__main__":

    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = ReaperAgent(path_resolution, command_line_args)
    agent.boot()