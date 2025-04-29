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
import threading

from agent.core.boot_agent import BootAgent
#from agent.core.class_lib.processes.reaper import Reaper  # Import Big Reaperfrom agent.core.class_lib.processes.reaper import Reaper  # Big Reaper
from agent.core.class_lib.processes.reaper_permanent_id_handler import ReaperPermanentIdHandler  # PID Handler

class ReaperAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        """
        Initialize the ReaperAgent with the necessary configurations.
        """
        super().__init__(path_resolution, command_line_args)

        # Load targets, kill ID, and initialize paths
        config = tree_node.get("config", {})
        self.targets = command_line_args.get("targets") or config.get("kill_list", [])
        self.perm_ids = command_line_args.get("perm_ids") or config.get("perm_ids", {})
        self.kill_id = command_line_args.get("kill_id") or config.get("kill_id") or f"reap-{int(time.time())}"
        self.outbox_path = os.path.join(self.path_resolution['comm_path'], "matrix", "outbox")
        os.makedirs(self.outbox_path, exist_ok=True)

        self.permanent_id_handler = ReaperPermanentIdHandler(self.path_resolution['pod_path'], self.path_resolution['comm_path'], logger=self.logger)


    def post_boot(self):
        """
        Logs the mission details and starts the mission in a separate thread.
        """
        self.log(f"[DISPOSABLE-REAPER] Mission {self.kill_id} received with targets: {self.targets}")
        threading.Thread(target=self.mission, daemon=True).start()

    def mission(self):
        """
        Execute the mission using the Permanent ID handler to process shutdown requests for all targets.
        """
        self.log("[INFO] Inserting hit team...")

        # Filter `self.targets` based on valid perm_ids
        filtered_perm_ids = {perm_id: self.perm_ids[perm_id] for perm_id in self.targets if perm_id in self.perm_ids}

        if not filtered_perm_ids:
            self.log("[WARNING] No valid targets found in the provided target list.")
            self.running = False  # Mark the agent as stopped
            return

        # Use central handler to process all valid targets at once
        try:
            self.permanent_id_handler.process_all_permanent_ids(filtered_perm_ids, tombstone_mode=True, wait_seconds=20)
            self.log("[INFO] Mission completed successfully.")
        except Exception as e:
            self.log(f"[ERROR] Failed to complete mission: {str(e)}")

        self.running = False  # Mark the agent as stopped
        self.log("[INFO] Mission completed and the agent is now stopping.")
        self.leave_tombstone_and_die()

    def leave_tombstone_and_die(self):
        """
        Reaper drops his own tombstone and shuts down cleanly.
        """
        try:

            incoming_dir = os.path.join(self.path_resolution["comm_path"], self.command_line_args["permanent_id"], "incoming")
            os.makedirs(incoming_dir, exist_ok=True)

            pod_dir = os.path.join(self.path_resolution["pod_path"], self.command_line_args["install_name"])

            # Write tombstone to comm
            die_path = os.path.join(incoming_dir, "die")
            with open(die_path, "w") as f:
                f.write("true")

            # Write tombstone to comm
            tombstone_path = os.path.join(incoming_dir, "tombstone")
            with open(tombstone_path, "w") as f:
                f.write("true")

            # Write tombstone to pod
            tombstone_path = os.path.join(pod_dir, "tombstone")
            with open(tombstone_path, "w") as f:
                f.write("true")

            self.log(f"[DISPOSABLE-REAPER] Die cookie dropped & Tombstone dropped. Mission complete. Signing off.")

        except Exception as e:
            self.log(f"[DISPOSABLE-REAPER][ERROR] Failed to leave tombstone: {str(e)}")

        finally:
            self.running = False  # Always stop running, even if tombstone writing fails

    def attempt_kill(self, perm_id):
        """
        Deliver 'die' and 'tombstone' signals to a directory and wait for graceful shutdown.
        Escalates with Permanent ID Handler if the process resists termination.
        """
        # Paths for the target
        pod_path = os.path.join(self.path_resolution['pod_path'], perm_id)
        comm_path = os.path.join(self.path_resolution['comm_path'], perm_id)

        # Send 'die' and 'tombstone' signals via `comm_path`
        incoming = os.path.join(comm_path, "incoming")
        os.makedirs(incoming, exist_ok=True)
        with open(os.path.join(incoming, "die"), "w") as f:
            json.dump({"cmd": "die", "force": False}, f)
        with open(os.path.join(incoming, "tombstone"), "w") as f:
            f.write("true")

        self.log(f"[DISPOSABLE-REAPER] Die and tombstone delivered to {perm_id}")

        # Monitor shutdown success via hello.moto file
        hello_path = os.path.join(pod_path, "hello.moto")
        max_wait = 18
        elapsed = 0
        while elapsed < max_wait:
            if not os.path.exists(hello_path):
                self.log(f"[DISPOSABLE-REAPER] {perm_id} down gracefully.")
                return True
            time.sleep(3)
            elapsed += 3

        # Escalate with PID handler if process resists
        self.log(f"[DISPOSABLE-REAPER] {perm_id} resisted — invoking Full PID Handler escalation.")
        self.escalate_with_pid_handler(perm_id)
        return False

    def escalate_with_pid_handler(self, perm_id):
        """
        Escalate the shutdown process using the Permanent ID handler for the specified target.
        """
        try:
            self.permanent_id_handler.shutdown_processes(perm_id, perm_id)
            self.log(f"[DISPOSABLE-REAPER] PID Handler escalation complete for {perm_id}")
        except Exception as e:
            self.log(f"[DISPOSABLE-REAPER] PID Handler escalation FAILED for {perm_id}: {e}")

    def send_mission_report(self, results):
        """
        Generate and save a mission report including results for each target.
        """
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
