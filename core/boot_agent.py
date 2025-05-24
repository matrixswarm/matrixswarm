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
from core.class_lib.packet_delivery.mixin.packet_factory_mixin import PacketFactoryMixin
from core.class_lib.packet_delivery.mixin.packet_delivery_factory_mixin import PacketDeliveryFactoryMixin

from core.boot_agent_thread_config import get_default_thread_registry

class BootAgent(PacketFactoryMixin, PacketDeliveryFactoryMixin):

    if __name__ == "__main__":

        raise RuntimeError("Direct execution of agents is forbidden. Only Matrix may be launched via bootloader.")

    def __init__(self, path_resolution, command_line_args, tree_node=None):

        # 🔐 Secure Key Injection (Ghost State)
        self.secure_keys = None

        # Detect keypipe path or direct key blob


        self.running = False

        self.path_resolution = path_resolution

        self.command_line_args = command_line_args

        self.tree_node = tree_node or {}

        self.boot_time = time.time()

        self.logger = Logger(self.path_resolution["comm_path_resolved"], "logs", "agent.log")

        self.subordinates=[]

        # Injected timeout-aware thread registry
        self.thread_registry = get_default_thread_registry()


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
                    now = time.time()
                    f.write(str(now))
                    print(f"[HEARTBEAT] Touched last.ping for {ping_file} -> {now}")
            except Exception as e:
                print(f"[HEARTBEAT][ERROR] Failed to write ping: {e} -> {ping_file} -> {now}")
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
                    f"[ENFORCE] {self.command_line_args['universal_id']} detected a newer process with job label: --job {job_label} — standing down.")
            else:
                print(
                    f"[ENFORCE] {self.command_line_args['universal_id']} verified as primary instance for --job {job_label} — proceeding with mission.")
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

    def monitor_threads(self):
        while self.running:
            # Only monitor if worker_thread exists
            if hasattr(self, "worker_thread") and self.worker_thread and not self.worker_thread.is_alive():
                self.log("[WATCHDOG] worker() thread has crashed. Logging beacon death.")
                self.emit_dead_poke("worker", "Worker thread crashed unexpectedly.")
                self.running = False
                os._exit(1)
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



    def is_worker_overridden(self):
        return self.__class__.worker != BootAgent.worker

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
        self.thread_registry["worker"]["active"] = self.is_worker_overridden()

        threading.Thread(target=self.enforce_singleton, name="enforce_singleton", daemon=True).start()
        self.thread_registry["enforce_singleton"]["active"] = True
        threading.Thread(target=self.heartbeat, name="heartbeat", daemon=True).start()
        self.thread_registry["heartbeat"]["active"] = True
        threading.Thread(target=self.spawn_manager, name="spawn_manager", daemon=True).start()
        self.thread_registry["spawn_manager"]["active"] = True
        threading.Thread(target=self.command_listener, name="cmd_listener", daemon=True).start()
        self.thread_registry["cmd_listener"]["active"] = True
        threading.Thread(target=self.reflex_listener, name="reflex_listener", daemon=True).start()
        self.thread_registry["reflex_listener"]["active"] = True
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
        emit_beacon = self.check_for_thread_poke("cmd_listener", 5)
        while self.running:
            try:
                emit_beacon()
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
        self.log("[REFLEX] Listening for .msg and .prompt reflex queries...")
        emit_beacon = self.check_for_thread_poke("reflex_listener", 5)
        while self.running:
            try:
                emit_beacon()

                for fname in os.listdir(inbox_path):
                    fpath = os.path.join(inbox_path, fname)

                    # 🎯 PROMPT HANDLER
                    if fname.endswith(".prompt"):
                        try:
                            with open(fpath, "r") as f:
                                prompt = f.read().strip()
                            os.remove(fpath)
                            if hasattr(self, "msg_prompt"):
                                self.msg_prompt(prompt,
                                                {"type": "prompt", "source": self.command_line_args["universal_id"]})
                                self.log(f"[REFLEX] ✅ Executed handler: msg_prompt")
                            else:
                                self.log("[REFLEX][MISS] No msg_prompt handler defined.")
                        except Exception as e:
                            self.log(f"[REFLEX][PROMPT-ERROR] {fname}: {e}")
                        continue

                    # 🎯 MSG HANDLER
                    if not fname.endswith(".msg"):
                        continue

                    try:
                        with open(fpath, "r") as f:
                            packet = json.load(f)
                    except Exception as e:
                        self.log(f"[REFLEX][PARSE-ERROR] {fname}: {e}")
                        continue

                    os.remove(fpath)
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

    def save_to_trace_session(self, packet, msg_type="msg"):
        tracer_id = packet.get("tracer_session_id")
        packet_id = packet.get("packet_id")

        if not tracer_id:
            self.log(f"[TRACE][SKIP] Invalid trace packet: tracer={tracer_id}, packet_id={packet_id}")
            return

        comm_root = os.path.normpath(self.path_resolution["comm_path"])
        parent_dir, last_component = os.path.split(comm_root)

        if last_component != "comm":
            self.log(f"[TRACE][ERROR] comm_path doesn't end in 'comm': {comm_root}")
            return

        base_dir = os.path.join(parent_dir, "boot_sessions", tracer_id)
        os.makedirs(base_dir, exist_ok=True)

        fname = f"{packet_id:03d}.{msg_type}"
        full_path = os.path.join(base_dir, fname)

        try:
            with open(full_path, "w") as f:
                json.dump(packet, f, indent=2)
        except Exception as e:
            self.log(f"[TRACE][ERROR] Failed to write trace packet {fname}: {e}")

    def _throttled_worker_wrapper(self):
        self.log("[BOOT] Throttled worker wrapper engaged.")
        emit_beacon = self.check_for_thread_poke("worker", 5)
        # 🔹 Optional pre-hook (called ONCE before loop)
        if hasattr(self, "worker_pre"):
            try:
                self.worker_pre()
                self.resolve_factory_injections()
            except Exception as e:
                self.log(f"[WORKER_PRE][ERROR] {e}")

        while self.running:
            if getattr(self, "can_proceed", True):
                try:
                    self.can_proceed = False

                    if self.is_worker_overridden():
                        self.log(f"[WORKER] Executing worker cycle...")
                        self.worker()

                    else:
                        if not hasattr(self, "_worker_skip_logged"):
                            self.log("[BOOT] No worker() override detected — skipping worker loop.")
                            self._worker_skip_logged = True

                    emit_beacon()
                except Exception as e:
                    self.emit_dead_poke("worker", str(e))
                    self.log(f"[WORKER][ERROR] {e}")

            else:

                time.sleep(0.05)

        # 🔹 Optional post-hook (called ONCE after loop exits)
        if hasattr(self, "worker_post"):
            try:
                self.worker_post()
            except Exception as e:
                self.log(f"[WORKER_POST][ERROR] {e}")

    #used to verify and map threads to verify consciousness
    def check_for_thread_poke(self, thread_token="worker", interval=5):
        timeout = self.thread_registry.get(thread_token, {}).get("timeout", 8)
        poke_path = os.path.join(self.path_resolution["comm_path_resolved"], "hello.moto", f"poke.{thread_token}")
        last_emit = [0]

        def emit():
            now = time.time()
            if now - last_emit[0] >= interval:
                with open(poke_path, "w") as f:
                    json.dump({
                        "status": "alive",
                        "last_seen": now,
                        "timeout": timeout,
                        "comment": f"Thread beacon from {thread_token}"
                    }, f, indent=2)
                last_emit[0] = now
                print(f"[BEACON] {thread_token} emitted at {now}")

        return emit

    def emit_dead_poke(self, thread_name, error_msg):
        path = os.path.join(self.path_resolution["comm_path_resolved"], "hello.moto", f"poke.{thread_name}")
        with open(path, "w") as f:
            json.dump({
                "status": "dead",
                "last_seen": time.time(),
                "error": error_msg
            }, f, indent=2)

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

    # Gets first level children of parent
    def get_node_by_role(self, role):
        """
        Consults the agent's own agent_tree.json (if present).
        Returns node dictionary for any direct subordinate matching given role.
        Hardened against missing or malformed trees.
        """
        try:
            tree_path = os.path.join(
                self.path_resolution['comm_path'],
                self.command_line_args['universal_id'],
                'agent_tree.json'
            )

            if not hasattr(self, '_cached_tree'):
                self._cached_tree = None
                self._tree_mtime = 0

            if os.path.exists(tree_path):
                mtime = os.path.getmtime(tree_path)
                if mtime != self._tree_mtime:
                    with open(tree_path, 'r') as f:
                        self._cached_tree = json.load(f)
                    self._tree_mtime = mtime

            if not self._cached_tree:
                self.log("[INTEL] No cached agent_tree found.")
                return None

            children = self._cached_tree.get("children", [])
            if not isinstance(children, list):
                self.log("[INTEL][ERROR] agent_tree children malformed.")
                return None

            for child in children:
                cfg = child.get("config", {})
                if cfg.get("role") == role:
                    return child

            self.log(f"[INTEL] No direct child with role '{role}' found.")
            return None

        except Exception as e:
            self.log(f"[INTEL][CRASH] get_node_by_role() failed: {e}")
            return None

    def get_nodes_by_role(self, role):
        """
        Returns a list of all direct children matching the given role.
        """
        try:
            tree_path = os.path.join(
                self.path_resolution['comm_path'],
                self.command_line_args['universal_id'],
                'agent_tree.json'
            )

            if not hasattr(self, '_cached_tree'):
                self._cached_tree = None
                self._tree_mtime = 0

            if os.path.exists(tree_path):
                mtime = os.path.getmtime(tree_path)
                if mtime != self._tree_mtime:
                    with open(tree_path, 'r') as f:
                        self._cached_tree = json.load(f)
                    self._tree_mtime = mtime

            if not self._cached_tree:
                self.log("[INTEL] No cached agent_tree found.")
                return []

            children = self._cached_tree.get("children", [])
            if not isinstance(children, list):
                self.log("[INTEL][ERROR] agent_tree children malformed.")
                return []

            matches = []
            for child in children:
                cfg = child.get("config", {})
                if cfg.get("role") == role:
                    matches.append(child)

            if not matches:
                self.log(f"[INTEL] No children with role '{role}' found.")
            return matches

        except Exception as e:
            self.log(f"[INTEL][CRASH] get_nodes_by_role() failed: {e}")
            return []

    #orginizes level one children by role
    def track_direct_subordinates(self):
        for child in self.tree_node.get("children", []):
            role = child.get("config", {}).get("role")
            uid = child.get("universal_id")
            if role and uid:
                self.subordinates[role] = uid
        self.log(f"[INTEL] Subordinate registry: {self.subordinates}")

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


        spawner = CoreSpawner(site_root_path=self.path_resolution["site_root_path"], python_site=self.path_resolution["python_site"], detected_python=self.path_resolution["python_exec"])

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
