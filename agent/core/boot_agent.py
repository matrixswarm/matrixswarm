#Authored by Daniel F MacDonald and ChatGPT
import os
import time
import traceback
from string import Template
from agent.core.agent import Agent
import threading
from datetime import datetime
from agent.core.class_lib.time_utils.time_passed import TimePassed
from agent.core.class_lib.time_utils.heartbeat_checker import last_heartbeat_delta
from agent.core.core_spawner import CoreSpawner
from agent.core.class_lib.processes.duplicate_job_check import  DuplicateProcessCheck
from agent.core.class_lib.file_system.util.json_safe_write import JsonSafeWrite

class BootAgent(Agent):

    def boot(self):
        self.pre_boot()

        cp = CoreSpawner()
        fail_success, self.boot_log = cp.get_boot_log(self.path_resolution["pod_path_resolved"])
        if not (fail_success and self.boot_log.get("permanent_id")):
            return

        self.running = True

        self.worker_thread = threading.Thread(target=self._throttled_worker_wrapper, name="worker", daemon=False)
        self.worker_thread.start()

        threading.Thread(target=self.enforce_singleton, name="enforce_singleton", daemon=True).start()
        threading.Thread(target=self.heartbeat, name="heartbeat", daemon=True).start()
        threading.Thread(target=self.spawn_manager, name="spawn_manager", daemon=True).start()
        threading.Thread(target=self.command_listener, name="cmd_listener", daemon=True).start()
        self.start_dynamic_throttle()
        self.post_boot()
        self.monitor_threads()

    def worker(self):
        self.log("[BOOT] Default worker loop running. Override me.")
        while self.running:
            time.sleep(5)


    def pre_boot(self):
        self.log("[BOOT] Default pre_boot (override me if needed)")

    def post_boot(self):
        self.log("[BOOT] Default post_boot (override me if needed)")

    def command_listener(self):
        self.log("[COMMAND] No command_listener implemented. Skipping.")

    def _throttled_worker_wrapper(self):
        self.log("[BOOT] Throttled worker wrapper engaged.")
        while self.running:
            if getattr(self, "can_proceed", True):
                self.can_proceed = False
                self.worker()
            else:
                time.sleep(0.05)

    def start_dynamic_throttle(self, min_delay=2, max_delay=10, max_load=2.0):
        def dynamic_throttle_loop():
            while self.running:
                try:
                    load_avg = os.getloadavg()[0]
                    scale = min(1.0, (load_avg - max_load) / max_load) if load_avg > max_load else 0
                    delay = int(min_delay + scale * (max_delay - min_delay))
                    if scale > 0:
                        self.log(f"[THROTTLE] Load: {load_avg:.2f} → delay: {delay}s")
                    self.can_proceed = True
                    time.sleep(delay)
                except Exception as e:
                    self.log(f"[THROTTLE-ERR] {e}")
                    time.sleep(min_delay)

        self.can_proceed = False
        threading.Thread(target=dynamic_throttle_loop, daemon=True).start()


    def spawn_manager(self):

        time_delta_timeout = 60

        from agent.core.tree_parser import TreeParser

        comm_file_spec = [
            {"name": "hello.moto", "type": "d", "content": None},
            {"name": "incoming", "type": "d", "content": None}
        ]

        #last_snapshot = {}
        orbits = {}
        spawner = CoreSpawner()
        #self.request_tree_slice_from_matrix()

        last_tree_mtime = 0
        tree = None  # Initial tree holder

        tree_path = os.path.join(self.path_resolution['comm_path'], self.command_line_args["permanent_id"], 'agent_tree.json')

        tree_refresh_time = 0

        while self.running:

            try:

                #   If we never checked for a slice or the time we last check if greater than 2 mins--recheck
                # 1==3 shut off for now
                if 1==3 and (tree_refresh_time == 0 or TimePassed.get_time_passed(tree_refresh_time) > 120):
                    #TELL MATRIX WE WANT OUR SLICE OF THE PIE
                    self.request_tree_slice_from_matrix()
                    tree_refresh_time = datetime.now().strftime("%Y%m%d%H%M%S%")

                print(f"[SPAWN] Checking for delegated children of {self.command_line_args['permanent_id']}")

                if not os.path.exists(tree_path):
                    time.sleep(5)
                    continue

                mtime = os.path.getmtime(tree_path)
                if mtime != last_tree_mtime:
                    tree = TreeParser.load_tree(tree_path)
                    last_tree_mtime = mtime
                    self.log(f"[SPAWN] Tree updated from disk.")

                if not tree:
                    print(f"[SPAWN][ERROR] Could not load tree for {self.command_line_args['permanent_id']}")
                    time.sleep(5)
                    continue
                else:
                    print(f"[SPAWN] Tree loaded, looking for children of {self.command_line_args['permanent_id']}")
                if not tree:
                    time.sleep(5)
                    continue

                #delta = self.check_delegation_changes(tree, last_snapshot)

                #for perm_id, node in delta["added"].items():
                for child_id in tree.get_first_level_child_ids(self.command_line_args["permanent_id"]):

                    node = tree.nodes.get(child_id)

                    if not node:
                        self.log(f"[SPAWN] Could not find node for {child_id}")
                        continue

                    #print(f"[SPAWN] Agent added: {self.command_line_args['permanent_id']} Node: {node}\n")

                    #IS THERE A DIE TOKEN IN THE TARGET'S INCOMING FOLDER
                    die_file = os.path.join(self.path_resolution['comm_path'], node.get("permanent_id"), 'incoming', 'die')
                    if os.path.exists(die_file):
                        self.log(f"[SPAWN-BLOCKED] {node.get("permanent_id")} has die file.")
                        continue

                    #IS THERE A DUPLICATE JOB
                    #job_label = f"{self.command_line_args['universe_id']}:{self.command_line_args['permanent_id']}:{node.get("permanent_id")}:{node.get("permanent_id")}"
                    #if DuplicateProcessCheck.check_all_duplicate_risks(job_label=job_label):
                    #    self.log(f"[SPAWN-BLOCKED] Duplicate process for {job_label}")
                    #    continue

                    #DID WE ALREADY PROCESS THIS FILE
                    processed = node.get("permanent_id") in orbits
                    last_processed = 0
                    if processed:
                        last_processed  = TimePassed.get_time_passed(orbits[node.get("permanent_id")]["last_check"])
                    # HAS THE LAST HEARTBEAT TIMESTAMP BEEN WITHIN ACCEPTABLE TIMEFRAME
                    #   We already processed file
                    #       No Hello.Moto Timestamp Found and not None
                    #       OR the Hello.Moto Timestamp doesn't show activity within acceptable timeframe
                    #       AND the Orbit last-time processed is within acceptable range
                    #           Continue Loop
                    #   ELSE Spawn the node

                    time_delta = last_heartbeat_delta(self.path_resolution['comm_path'], node.get("permanent_id"))
                    if time_delta is not None and time_delta < time_delta_timeout:
                        continue

                    spawner.ensure_comm_channel(node.get("permanent_id"), comm_file_spec, node.get("filesystem", {}))  # ✅ Extract only the filesystem block)
                    new_uuid, pod_path = spawner.create_runtime(node.get("permanent_id"))
                    pid, cmd = spawner.spawn_agent(
                        self.command_line_args["universe_id"],
                        new_uuid,
                        node.get("name"),
                        node.get("permanent_id"),
                        self.command_line_args["permanent_id"],
                        tree_node=node,  # ← inject tree node directly
                    )

                    orbits[node.get("permanent_id")] = {
                        "permanent_id": node.get("permanent_id"),
                        "name": node.get("name"),
                        "pid": pid,
                        "cmd": cmd,
                        "uuid": new_uuid,
                        "last_check": datetime.now().strftime("%Y%m%d%H%M%S%")
                    }


                #for perm_id in delta["removed"]:
                #    self.log(f"[DELEGATION] Agent removed: {perm_id}")
                    # Optional: issue die, or mark for scavenger

                #last_snapshot = tree.query_children_by_id(self.command_line_args["permanent_id"])

            except Exception as e:
                # Get the full traceback information
                tb = traceback.format_exc()
                # Log or print the detailed error message and line number
                print(f"[SPAWN] Exception occurred: {e}")
                print(f"[SPAWN] Full traceback:\n{tb}")

            time.sleep(10)

    #request_tree_slice_from_matrix part of the tree that this agent is delegated to maintain
    def request_tree_slice_from_matrix(self):
        #   GET MATRIX COMM PATH
        #       CREATE COMMAND
        #       WRITE THE COMMAND TO MATRIX COMM PATH USING ATOMIC WRITE
        path = Template(self.path_resolution["incoming_path_template"])
        matrix_incoming_path = path.substitute(permanent_id=self.command_line_args["matrix"])

        request = self.command_line_args["permanent_id"] + ":_tree_slice_request.cmd"

        JsonSafeWrite.safe_write(os.path.join(matrix_incoming_path, request),  '1')

        self.log(f"[TREE_SLICE_REQUEST] Sent request to matrix from {self.command_line_args["permanent_id"]}.")

    def command_listener(self):
        print("Override command_listener() in subclass.")


