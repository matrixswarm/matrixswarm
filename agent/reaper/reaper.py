#Authored by Daniel F MacDonald and ChatGPT
# ╔═══════════════════════════════════════════════╗
# ║              ☠ REAPER AGENT ☠                ║
# ║   Tactical Cleanup · Wipe Authority · V2.5    ║
# ║        Forged in the halls of Matrix          ║
# ║  Accepts: .cmd / .json  |  Modes: soft/full   ║
# ╚═══════════════════════════════════════════════╝

# ======== 🛬 LANDING ZONE BEGIN 🛬 ========"
# ======== 🛬 LANDING ZONE END 🛬 ========"

# DisposableReaperAgent.py
import os
import json
import time
import threading

from core.boot_agent import BootAgent
#from core.class_lib.processes.reaper import Reaper  # Import Big Reaperfrom core.class_lib.processes.reaper import Reaper  # Big Reaper
from core.class_lib.processes.reaper_universal_id_handler import ReaperUniversalHandler  # PID Handler

class Agent(BootAgent):
    def __init__(self, path_resolution, command_line_args, tree_node):
        super().__init__(path_resolution, command_line_args, tree_node)


        # Load targets, kill ID, and initialize paths
        config = self.tree_node.get("config", {})

        self.targets = command_line_args.get("targets") or config.get("kill_list", [])
        self.universal_ids = command_line_args.get("universal_ids") or config.get("universal_ids", {})
        self.kill_id = command_line_args.get("kill_id") or config.get("kill_id") or f"reap-{int(time.time())}"
        self.strike_delay = config.get("delay", 0)
        self.tombstone_comm = config.get("tombstone_comm", True)
        self.tombstone_pod = config.get("tombstone_pod", True)
        self.cleanup_die = config.get("cleanup_die", False)
        self.outbox_path = os.path.join(self.path_resolution['comm_path'], "matrix", "outbox")
        os.makedirs(self.outbox_path, exist_ok=True)

        self.universal_id_handler = ReaperUniversalHandler(self.path_resolution['pod_path'], self.path_resolution['comm_path'], logger=self.logger)

    def post_boot(self):
        """
        Logs the mission details and starts the mission in a separate thread.
        """
        self.log(f"[DISPOSABLE-REAPER] Mission {self.kill_id} received with targets: {self.targets}")
        threading.Thread(target=self.mission, daemon=True).start()

    def worker_pre(self):
        self.log("[REAPER] Agent entering execution mode. Targets loaded. Blades sharp.")

    def worker_post(self):
        self.log("[REAPER] Mission completed. Reaper dissolving into silence.")

    def mission(self):
        """
        Execute the mission using the Permanent ID handler to process shutdown requests for all targets.
        """
        self.log("[INFO] Inserting hit team...")

        if self.strike_delay > 0:
            self.log(f"[REAPER] ⏱ Waiting {self.strike_delay} seconds before executing strike...")
            time.sleep(self.strike_delay)

        # Filter `self.targets` based on valid universal_ids
        filtered_universal_ids = {universal_id: self.universal_ids[universal_id] for universal_id in self.targets if universal_id in self.universal_ids}

        if not filtered_universal_ids:
            self.log("[WARNING] No valid targets found in the provided target list.")
            self.running = False  # Mark the agent as stopped
            return

        # Use central handler to process all valid targets at once
        try:

            self.universal_id_handler.process_all_universal_ids(
                filtered_universal_ids,
                tombstone_mode=True,
                wait_seconds=20,
                tombstone_comm=self.tombstone_comm,
                tombstone_pod=self.tombstone_pod
            )
            if self.cleanup_die:
                for uid in filtered_universal_ids:
                    try:
                        die_path = os.path.join(self.path_resolution["comm_path"], uid, "incoming", "die")
                        if os.path.exists(die_path):
                            os.remove(die_path)
                            self.log(f"[REAPER] Removed die signal from comm: {uid}")
                    except Exception as e:
                        self.log(f"[REAPER][ERROR] Failed to remove die for {uid}: {e}")

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

            incoming_dir = os.path.join(self.path_resolution["comm_path"], self.command_line_args["universal_id"], "incoming")
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

    def attempt_kill(self, universal_id):
        """
        Deliver 'die' and 'tombstone' signals to a directory and wait for graceful shutdown.
        Escalates with Permanent ID Handler if the process resists termination.
        """
        # Paths for the target
        pod_path = os.path.join(self.path_resolution['pod_path'], universal_id)
        comm_path = os.path.join(self.path_resolution['comm_path'], universal_id)

        # Send 'die' and 'tombstone' signals via `comm_path`
        incoming = os.path.join(comm_path, "incoming")
        os.makedirs(incoming, exist_ok=True)
        with open(os.path.join(incoming, "die"), "w") as f:
            json.dump({"cmd": "die", "force": False}, f)
        with open(os.path.join(incoming, "tombstone"), "w") as f:
            f.write("true")

        self.log(f"[DISPOSABLE-REAPER] Die and tombstone delivered to {universal_id}")

        # Monitor shutdown success via hello.moto file
        hello_path = os.path.join(pod_path, "hello.moto")
        max_wait = 18
        elapsed = 0
        while elapsed < max_wait:
            if not os.path.exists(hello_path):
                self.log(f"[DISPOSABLE-REAPER] {universal_id} down gracefully.")
                return True
            time.sleep(3)
            elapsed += 3

        # Escalate with PID handler if process resists
        self.log(f"[DISPOSABLE-REAPER] {universal_id} resisted — invoking Full PID Handler escalation.")
        self.escalate_with_pid_handler(universal_id)
        return False

    def escalate_with_pid_handler(self, universal_id):
        """
        Escalate the shutdown process using the Permanent ID handler for the specified target.
        """
        try:
            self.universal_id_handler.shutdown_processes(universal_id, universal_id)
            self.log(f"[DISPOSABLE-REAPER] PID Handler escalation complete for {universal_id}")
        except Exception as e:
            self.log(f"[DISPOSABLE-REAPER] PID Handler escalation FAILED for {universal_id}: {e}")

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
    agent = Agent(path_resolution, command_line_args, tree_node)
    agent.boot()