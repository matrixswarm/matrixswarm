#Authored by Daniel F MacDonald and ChatGPT
import sys
import os
import json

if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])

import time
import psutil

# Now you can import your module
from agent.core.boot_agent import BootAgent
from agent.core.mixin.delegation import DelegationMixin

class WorkerAgent(BootAgent, DelegationMixin):

    def __init__(self, path_resolution, command_line_args):

        super().__init__(path_resolution, command_line_args)

        self.path_resolution = path_resolution

        self.command_line_args = command_line_args

        self.orbits = {}

    def pre_boot(self):
        print("")

    def post_boot(self):
        self.log("[WORKER] Post-boot complete. Agent standing by.")


    def worker(self):

        print("[RUN] WorkerAgent main loop running...")

        while self.running:

            print("Doing my thing...")
            time.sleep(10)

            if self.command_line_args["permanent_id"] == "worker-backup-2":

                load_averages = os.getloadavg()  # Returns a tuple: (1_min, 5_min, 15_min)

                # Print the load averages
                print(f"Load averages:")
                print(f"1-minute: {load_averages[0]}")
                print(f"5-minute: {load_averages[1]}")
                print(f"15-minute: {load_averages[2]}")

            elif self.command_line_args["permanent_id"] == "worker-backup-1":

                net_stats = psutil.net_io_counters()

                print(f"Bytes Sent: {net_stats.bytes_sent}")
                print(f"Bytes Received: {net_stats.bytes_recv}")
                print(f"Packets Sent: {net_stats.packets_sent}")
                print(f"Packets Received: {net_stats.packets_recv}")
                print(f"Errors In: {net_stats.errin}")
                print(f"Errors Out: {net_stats.errout}")
                print(f"Dropped Packets In: {net_stats.dropin}")
                print(f"Dropped Packets Out: {net_stats.dropout}")

            elif self.command_line_args["permanent_id"] == "worker-backup-3":
                import tracemalloc
                tracemalloc.start()
                snapshot = tracemalloc.take_snapshot()
                top_stats = snapshot.statistics("lineno")
                for stat in top_stats[:10]:
                    print(stat)

            print("watching...")
            #COMMAND CENTER


    def process_command(self, command):
        if command.get("action") == "update_delegates":
            self.log("[COMMAND] Delegate update received. Saving tree and spawning.")

            tree_snapshot = command.get("tree_snapshot")
            if not tree_snapshot:
                self.log("[COMMAND] No tree_snapshot found in command.")
                return

            tree_path = os.path.join(
                self.path_resolution["comm_path"],
                self.command_line_args["permanent_id"],
                "agent_tree.json"
            )

            try:
                with open(tree_path, "w") as f:
                    json.dump(tree_snapshot, f, indent=2)
                self.log("[COMMAND] Tree snapshot saved.")
                self.spawn_manager()
            except Exception as e:
                self.log(f"[COMMAND] Failed to save tree: {e}")

if __name__ == "__main__":
    # label = None
    # if "--label" in sys.argv:
    #   label = sys.argv[sys.argv.index("--label") + 1]

    pid = os.getpid()

    # current directory of the agent script or it wont be able to find itself
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))

    worker = WorkerAgent(path_resolution, command_line_args)

    worker.boot()
