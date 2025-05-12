#Authored by Daniel F MacDonald and ChatGPT
import os
import time
import traceback
import threading
import json
import importlib
import inspect
from core.class_lib.time_utils.heartbeat_checker import last_heartbeat_delta
from core.core_spawner import CoreSpawner
from core.class_lib.file_system.util.json_safe_write import JsonSafeWrite
from core.path_manager import PathManager
from string import Template
from core.class_lib.file_system.find_files_with_glob import  FileFinderGlob
from core.class_lib.processes.duplicate_job_check import  DuplicateProcessCheck
from core.class_lib.logging.logger import Logger


class BootAgent():

    if __name__ == "__main__":

        raise RuntimeError("Direct execution of agents is forbidden. Only Matrix may be launched via bootloader.")

    def __init__(self, path_resolution, command_line_args, tree_node=None):

        self.running = False

        self.path_resolution = path_resolution

        self.command_line_args = command_line_args

        self.tree_node = tree_node or {}

        self.boot_time = time.time()

        self.logger = Logger(self.path_resolution["comm_path_resolved"], "logs", "agent.log")

    def log(self, message):
        self.logger.log(message)

    def send_message(self, message):
        self.log(f"[SEND] {json.dumps(message)}")

        # sends a heartbeat to comm/{universal_id}/hello.moto of self

    def heartbeat(self):
        hello_path = os.path.join(self.path_resolution["comm_path_resolved"], "hello.moto")
        ping_file = os.path.join(hello_path, "last.ping")

        os.makedirs(hello_path, exist_ok=True)

        while self.running:
            try:
                with open(ping_file, "w") as f:
                    f.write(self.command_line_args["install_name"])
                # self.log(f"[HEARTBEAT] Touched last.ping for {self.command_line_args['install_name']}")
            except Exception as e:
                self.log(f"[HEARTBEAT][ERROR] Failed to write ping: {e}")
            time.sleep(10)

    def enforce_singleton(self):

        # LOOP FOR 20 SECS; IF AN INSTANCE MATCHES THE JOB TAG, KILL PROGRAM
        # IF A DIE FILE IS FOUND IN THE INCOMING FOLDER, KILL PROGRAM
        while self.running:

            # is there any duplicate processes that have duplicate cli --job leave if this process is younger
            job_label = DuplicateProcessCheck.get_self_job_label()

            if DuplicateProcessCheck.check_all_duplicate_risks(job_label=job_label, check_path=False):
                self.running = False
                print(
                    f"[INFO]core.agent.py: enforce_singleton: {self.command_line_args["universal_id"]} : shutting down found job having a later timestamp \"--job {job_label}\"")
            else:
                print(
                    f"[INFO]core.agent.py: enforce_singleton: {self.command_line_args["universal_id"]} : safe to proceed no duplicate processes with label  \"--job {job_label}\"")

            # incoming:   die
            # example: change {root}/comm/{universal_id}/incoming = {root}/comm/worker-1/incoming
            #     look for die file in incoming only be 1 at anytime, and matrix command_thread will add/remove, spawn thread will
            #     check
            try:
                path = Template(self.path_resolution["incoming_path_template"])
            except KeyError:
                self.log("[ENFORCE] Missing incoming_path_template. Using fallback.")
                path = Template(os.path.join("comm", "$universal_id", "incoming"))

            path = path.substitute(universal_id=self.command_line_args["universal_id"])

            count, file_list = FileFinderGlob.find_files_with_glob(path, pattern="die")
            if count > 0:
                self.running = False
                print(
                    f"[INFO]core.agent.py: enforce_singleton: {self.command_line_args["universal_id"]} die cookie ingested, going down easy...")

            # within 20secs if another instance detected, and this is the younger of the die

            time.sleep(7)

    def mailman_manager(self):

        print('hi')

    def monitor_threads(self):
        while self.running:
            if not self.worker_thread.is_alive():
                self.log("[WATCHDOG] worker() thread has crashed. Shutting down agent.")
                self.running = False
                os._exit(1)  # 🔥 Force kill (or use sys.exit if you want softer)
            time.sleep(3)

    def resolve_factory_injections(self):
        self.log("[FACTORY] Starting factory injection from 'factories' block only.")

        config = self.tree_node.get("config", {})
        factories = config.get("factories", {})

        self.log(f"[FACTORY-INJECT] Found factories: {list(factories.keys())}")

        for dotted_path, factory_config in factories.items():
            if not isinstance(dotted_path, str) or "." not in dotted_path:
                self.log(f"[FACTORY-SKIP] Invalid factory path: {dotted_path}")
                continue

            try:
                full_module_path = f"agent.{self.command_line_args['agent_name']}.factory.{dotted_path}"
                self.log(f"[FACTORY] Attempting: {full_module_path}")
                mod = __import__(full_module_path, fromlist=["attach"])
                mod.attach(self, factory_config)
                self.log(f"[FACTORY] Loaded: {full_module_path}")
            except Exception as e:
                self.log(f"[FACTORY-ERROR] {dotted_path} → {e}")


    def boot(self):
        self.pre_boot()

        pm = PathManager(use_session_root=True, site_root_path=self.path_resolution["site_root_path"])
        cp = CoreSpawner(path_manager=pm)
        fail_success, self.boot_log = cp.get_boot_log(self.path_resolution["pod_path_resolved"])
        if not (fail_success and self.boot_log.get("universal_id")):

            return

        self.running = True

        self.worker_thread = threading.Thread(target=self._throttled_worker_wrapper, name="worker", daemon=False)
        self.worker_thread.start()

        threading.Thread(target=self.enforce_singleton, name="enforce_singleton", daemon=True).start()
        threading.Thread(target=self.heartbeat, name="heartbeat", daemon=True).start()
        threading.Thread(target=self.spawn_manager, name="spawn_manager", daemon=True).start()
        threading.Thread(target=self.command_listener, name="cmd_listener", daemon=True).start()
        threading.Thread(target=self.reflex_listener, name="reflex_listener", daemon=True).start()
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
        incoming_path = os.path.join(self.path_resolution["comm_path_resolved"], "incoming")
        os.makedirs(incoming_path, exist_ok=True)
        self.log("[COMMAND] Listening for standardized .cmd files...")

        while self.running:
            try:
                for fname in os.listdir(incoming_path):
                    if not fname.endswith(".cmd"):
                        continue

                    fpath = os.path.join(incoming_path, fname)
                    with open(fpath, "r") as f:
                        try:
                            packet = json.load(f)
                        except Exception as e:
                            self.log(f"[CMD][PARSE-FAIL] {fname}: {e}")
                            continue

                    os.remove(fpath)

                    cmd_type = packet.get("type")
                    content = packet.get("content", {})

                    if not cmd_type:
                        self.log(f"[CMD][SKIP] No 'type' field in: {fname}")
                        continue

                    handler_name = f"cmd_{cmd_type}"
                    if hasattr(self, handler_name):
                        try:
                            getattr(self, handler_name)(content, packet)
                            self.log(f"[CMD] ✅ Executed handler: {handler_name}")
                        except Exception as e:
                            self.log(f"[CMD][ERROR] {handler_name} crashed → {e}")
                    else:
                        self.log(f"[CMD][MISS] No handler for: {cmd_type}")

            except Exception as e:
                self.log(f"[CMD][LOOP-ERR] {e}")

            time.sleep(1)

    def reflex_listener(self):
        inbox_path = os.path.join(self.path_resolution["comm_path_resolved"], "incoming")
        os.makedirs(inbox_path, exist_ok=True)
        self.log("[REFLEX] Listening for .msg reflex queries...")

        while self.running:
            try:
                for fname in os.listdir(inbox_path):
                    if not fname.endswith(".msg"):
                        continue

                    path = os.path.join(inbox_path, fname)
                    with open(path, "r") as f:
                        try:
                            packet = json.load(f)
                            #self.log(f"[REFLEX][DEBUG] {fname} → {json.dumps(packet, indent=2)}")
                        except Exception as e:
                            self.log(f"[REFLEX][PARSE-ERROR] {fname}: {e}")
                            continue

                    os.remove(path)
                    msg_type = packet.get("type")
                    content = packet.get("content", {})

                    if not msg_type:
                        self.log(f"[REFLEX][SKIP] No 'type' in: {fname}")
                        continue

                    handler_name = f"msg_{msg_type}"
                    if hasattr(self, handler_name):
                        try:
                            getattr(self, handler_name)(content, packet)
                            self.log(f"[REFLEX] ✅ Executed handler: {handler_name}")
                        except Exception as e:
                            self.log(f"[REFLEX][ERROR] {handler_name} crashed → {e}")
                    else:
                        self.log(f"[REFLEX][MISS] No msg_* handler for: {msg_type}")

            except Exception as e:
                self.log(f"[REFLEX][LOOP-ERROR] {e}")
            time.sleep(1)

    def _throttled_worker_wrapper(self):
        self.log("[BOOT] Throttled worker wrapper engaged.")

        # 🔹 Optional pre-hook (called ONCE before loop)
        if hasattr(self, "worker_pre"):
            try:
                self.worker_pre()
                self.resolve_factory_injections()
            except Exception as e:
                self.log(f"[WORKER_PRE][ERROR] {e}")

        while self.running:
            if getattr(self, "can_proceed", True):
                self.can_proceed = False
                self.worker()
            else:
                time.sleep(0.05)

        # 🔹 Optional post-hook (called ONCE after loop exits)
        if hasattr(self, "worker_post"):
            try:
                self.worker_post()
            except Exception as e:
                self.log(f"[WORKER_POST][ERROR] {e}")

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

        from core.tree_parser import TreeParser

        last_tree_mtime = 0
        tree = None  # Initial tree holder

        tree_path = os.path.join(self.path_resolution['comm_path'], self.command_line_args["universal_id"], 'agent_tree.json')

        while self.running:
            try:
                print(f"[SPAWN] Checking for delegated children of {self.command_line_args['universal_id']}")

                if not os.path.exists(tree_path):
                    time.sleep(5)
                    continue

                mtime = os.path.getmtime(tree_path)
                if mtime != last_tree_mtime:
                    tree = TreeParser.load_tree(tree_path)
                    last_tree_mtime = mtime
                    self.log(f"[SPAWN] Tree updated from disk.")

                if not tree:
                    print(f"[SPAWN][ERROR] Could not load tree for {self.command_line_args['universal_id']}")
                    time.sleep(5)
                    continue

                for child_id in tree.get_first_level_child_ids(self.command_line_args["universal_id"]):

                    node = tree.nodes.get(child_id)
                    if not node:
                        self.log(f"[SPAWN] Could not find node for {child_id}")
                        continue

                    # Skip if die token exists
                    die_file = os.path.join(self.path_resolution['comm_path'], node.get("universal_id"), 'incoming', 'die')
                    if os.path.exists(die_file):
                        self.log(f"[SPAWN-BLOCKED] {node.get('universal_id')} has die file.")
                        continue

                    # Skip if recent heartbeat is alive
                    time_delta = last_heartbeat_delta(self.path_resolution['comm_path'], node.get("universal_id"))
                    if time_delta is not None and time_delta < time_delta_timeout:
                        continue

                    # Call new tactical spawn function
                    self.spawn_agent_direct(
                        universal_id=node.get("universal_id"),
                        agent_name=node.get("name"),
                        tree_node=node
                    )

            except Exception as e:
                tb = traceback.format_exc()
                print(f"[SPAWN] Exception occurred: {e}")
                print(f"[SPAWN] Full traceback:\n{tb}")

            time.sleep(10)

    def spawn_agent_direct(self, universal_id, agent_name, tree_node):


        spawner = CoreSpawner(site_root_path=self.path_resolution["site_root_path"])

        comm_file_spec = []

        # Ensure comm channel (basic folders)
        spawner.ensure_comm_channel(universal_id, comm_file_spec, tree_node.get("filesystem", {}))

        # Create pod runtime
        new_uuid, pod_path = spawner.create_runtime(universal_id)

        # Spawn the agent
        result = spawner.spawn_agent(
            spawn_uuid=new_uuid,
            agent_name=agent_name,
            universal_id=universal_id,
            spawner=self.command_line_args["universal_id"],
            tree_node=tree_node,
            universe_id=self.command_line_args.get("universe", "unknown")
        )

        if result is None:
            self.log(f"[MATRIX][KILL] ERROR: Failed to spawn agent {universal_id}.")
            return

        return result

    #request_tree_slice_from_matrix part of the tree that this agent is delegated to maintain
    def request_tree_slice_from_matrix(self):
        #   GET MATRIX COMM PATH
        #       CREATE COMMAND
        #       WRITE THE COMMAND TO MATRIX COMM PATH USING ATOMIC WRITE
        path = Template(self.path_resolution["incoming_path_template"])
        matrix_incoming_path = path.substitute(universal_id=self.command_line_args["matrix"])

        request = self.command_line_args["universal_id"] + ":_tree_slice_request.cmd"

        JsonSafeWrite.safe_write(os.path.join(matrix_incoming_path, request),  '1')

        self.log(f"[TREE_SLICE_REQUEST] Sent request to matrix from {self.command_line_args["universal_id"]}.")
