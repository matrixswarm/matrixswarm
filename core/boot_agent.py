#Authored by Daniel F MacDonald and ChatGPT
import os
import time
import traceback
import threading
import json
import hashlib
import fnmatch
from core.mixin.ghost_rider_ultra import GhostRiderUltraMixin

from core.class_lib.time_utils.heartbeat_checker import last_heartbeat_delta
from core.core_spawner import CoreSpawner
from core.path_manager import PathManager
from core.mixin.identity_registry import IdentityRegistryMixin
from core.utils.swarm_sleep import interruptible_sleep
from string import Template
from core.class_lib.file_system.find_files_with_glob import  FileFinderGlob
from core.class_lib.processes.duplicate_job_check import  DuplicateProcessCheck
from core.class_lib.logging.logger import Logger
from core.class_lib.packet_delivery.mixin.packet_factory_mixin import PacketFactoryMixin
from core.class_lib.packet_delivery.mixin.packet_delivery_factory_mixin import PacketDeliveryFactoryMixin
from core.class_lib.packet_delivery.mixin.packet_reception_factory_mixin import PacketReceptionFactoryMixin
from core.class_lib.packet_delivery.utility.encryption.config import ENCRYPTION_CONFIG

from core.class_lib.packet_delivery.utility.encryption.config import EncryptionConfig
from core.mixin.ghost_vault import decrypt_vault
from core.utils.trust_log import log_trust_banner
from core.mixin.ghost_vault import generate_agent_keypair
from core.boot_agent_thread_config import get_default_thread_registry
from core.trust_templates.matrix_dummy_priv import DUMMY_MATRIX_PRIV
from core.tree_parser import TreeParser

class BootAgent(PacketFactoryMixin, PacketDeliveryFactoryMixin, PacketReceptionFactoryMixin, GhostRiderUltraMixin, IdentityRegistryMixin):

    if __name__ == "__main__":

        raise RuntimeError("Direct execution of agents is forbidden. Only Matrix may be launched via bootloader.")

    def __init__(self):

        print("[BOOT] Matrix waking up...")

        try:
            payload = decrypt_vault()
            print("[VAULT] Decryption succeeded")
        except Exception as e:
            print(f"[FATAL] Vault decryption failed: {e}")
            exit()

        self.path_resolution = payload["path_resolution"]
        self.command_line_args = payload["args"]
        self.tree_node = payload["tree_node"]

        self.swarm_key = payload.get("swarm_key")
        self.matrix_pub = payload.get("matrix_pub")
        self.matrix_priv = payload.get("matrix_priv")  # Fallback already handled by decrypt_vault()

        self.matrix_pub_obj = None
        self.matrix_priv_obj = None

        self.public_key_obj = payload["public_key_obj"]
        self.private_key_obj = payload["private_key_obj"]
        self.pub_fingerprint = payload["pub_fingerprint"]
        self.secure_keys = payload.get("secure_keys", {})
        self.cached_pem = payload.get("cached_pem", {})
        config = EncryptionConfig()

        self.logger = Logger(self.path_resolution["comm_path_resolved"], "logs", "agent.log")

        self.encryption_enabled=bool(payload.get("encryption_enabled",0))
        if self.encryption_enabled:
            config.set_swarm_key(self.swarm_key)
            config.set_enabled(True)
            self.logger.set_encryption_key(self.swarm_key)

        # Optional fingerprint of Matrix public key
        try:
            self.matrix_fingerprint = hashlib.sha256(self.matrix_pub.encode()).hexdigest()[:12]
        except Exception as e:
            self.log(f"[BOOT] matrix_pub is missing. Trust cannot be verified. {e}")


        # Convert to objects
        from cryptography.hazmat.primitives import serialization

        try:
            self.matrix_pub_obj = serialization.load_pem_public_key(self.matrix_pub.encode())
        except Exception as e:
            self.matrix_pub_obj = None
            self.logger.log(f"[BOOT] matrix_pub is missing. Trust cannot be verified. {e}")

            exit()

        try:
            self.matrix_priv_obj = serialization.load_pem_private_key(self.matrix_priv.encode(), password=None)
        except Exception as e:
            self.matrix_priv_obj = None
            self.log(f"[TRUST][WARN] Matrix private key invalid or placeholder: {e}")
            exit()

        # 🧬 Chain-of-trust determination
        uid = self.command_line_args.get("universal_id", "")
        log_trust_banner(
            agent_name=uid,
            logger=self.logger,
            pub=self.secure_keys.get("pub"),
            matrix_pub=self.matrix_pub,
            matrix_priv=self.matrix_priv,
            swarm_key=self.swarm_key,
        )

        #this option will be pulled from the command line as debug
        #all packets all directives, using the self.swarm_key
        self.packet_encryption=True

        self.boot_time = time.time()
        self.running = False
        self.subordinates = []
        self.thread_registry = get_default_thread_registry()

        if self.encryption_enabled:
            config.set_public_key(self.public_key_obj)
            config.set_private_key(self.private_key_obj)
            config.set_matrix_public_key(self.matrix_pub_obj)
            config.set_matrix_private_key(self.matrix_priv_obj)

        self.verbose = bool(self.command_line_args.get('verbose',0))
        self._loaded_tree_nodes={}
        self._service_manager_services = {}

        self.running = False

    def log(self, message, **kwargs):
        if hasattr(self, "logger"):
            self.logger.log(message, **kwargs)
        else:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{ts}] [INFO] {message}")

    def send_message(self, message):
        self.log(f"[SEND] {json.dumps(message)}")

        # sends a heartbeat to comm/{universal_id}/hello.moto of self

    def heartbeat(self):
        hello_path = os.path.join(self.path_resolution["comm_path_resolved"], "hello.moto")
        ping_file = os.path.join(hello_path, "poke.heartbeat")

        os.makedirs(hello_path, exist_ok=True)

        while self.running:
            try:
                with open(ping_file, "w") as f:
                    now = time.time()
                    f.write(str(now))
                    print(f"[HEARTBEAT] Touched poke.heartbeat for {ping_file} -> {now}")
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

        try:
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
            threading.Thread(target=self.packet_listener, name="packet_listener", daemon=True).start()
            self.thread_registry["packet_listener"]["active"] = True
            self.start_dynamic_throttle()
            self.post_boot()
            self.monitor_threads()

        except Exception as e:
            print(f"[boot_agent][boot] Error: {e}")
            traceback.print_exc()

    def worker(self, config:dict = None):
        self.log("[BOOT] Default worker loop running. Override me.")
        while self.running:
            interruptible_sleep(self, 5)


    def pre_boot(self):
        self.log("[BOOT] Default pre_boot (override me if needed)")

    def post_boot(self):
        self.log("[BOOT] Default post_boot (override me if needed)")

    def packet_listener(self):
        self.log("[UNIFIED-LISTENER] Monitoring incoming packets...")
        incoming_path = os.path.join(self.path_resolution["comm_path_resolved"], "incoming")
        os.makedirs(incoming_path, exist_ok=True)
        emit_beacon = self.check_for_thread_poke("packet_listener", 5)
        last_dir_mtime = os.path.getmtime(incoming_path)

        try:

            ra = self.get_reception_agent("file.json_file", new=True)
            ra.set_location({"path": self.path_resolution["comm_path"]}) \
                .set_address([self.command_line_args["universal_id"]]) \
                .set_drop_zone({"drop": "incoming"})

        except Exception as e:
            self.log(f"[UNIFIED][ERROR] Failed to process: {e}")

        while self.running:

            try:

                emit_beacon()

                current_dir_mtime = os.path.getmtime(incoming_path)
                if current_dir_mtime != last_dir_mtime:
                    last_dir_mtime = current_dir_mtime

                    for fname in os.listdir(incoming_path):
                        if not fname.endswith(".json"):
                            continue
                        try:

                            pk = self.get_delivery_packet("standard.command.packet", new=True)
                            pk2 = self.get_delivery_packet("standard.general.json.packet", new=True)
                            pk.set_packet(pk2)

                            packet = ra.set_identifier(fname) \
                                       .set_packet(pk) \
                                       .receive()

                            fpath = os.path.join(incoming_path, fname)  # get the file's path
                            os.remove(fpath)

                            try:
                                pk = packet.get_packet()
                            except Exception as e:
                                self.log(f"[UNIFIED][ERROR] Failed to process {fname}: {e} :{pk}")
                                pk={}

                            if ra.get_error_success() or packet is None:
                                pk={}
                                self.log(f"Failed to receive data from reception agent or error: {ra.get_error_success_msg()}.")

                            handler = pk.get("handler")
                            if not handler:
                                self.log(f"[UNIFIED][SKIP] No 'call' in: {fname}")
                                continue

                            #self.log(f"#########{pk}xxxxxxxxxxxxxxxx")

                            handler_name = pk.get("handler")
                            content = pk.get("content", {})


                            # 1. Check if the class has a direct method with this name
                            handler_fn = getattr(self, handler_name, None)

                            if callable(handler_fn):
                                try:
                                    handler_fn(content, pk)
                                    self.log(f"[UNIFIED] ✅ Executed handler: {handler_name}")
                                    continue
                                except Exception as e:
                                    self.log(f"[UNIFIED][ERROR] Handler '{handler_name}' failed: {e}")

                            # 2. Fallback: Try to dynamically load a factory module
                            self.log(f"[UNIFIED][MISS] No direct handler '{handler_name}', attempting factory load...")

                            try:
                                # Clean up handler name (e.g. strip namespaces)
                                handler_id = handler_name.split(".")[-1]  # e.g. cmd_example
                                full_module_path = f"agent.{self.command_line_args['agent_name']}.factory.{handler_id}"

                                self.log(f"[FACTORY] Attempting: {full_module_path}")

                                mod = __import__(full_module_path, fromlist=["attach"])
                                mod.attach(self, {"packet": pk, "content": content})

                                self.log(f"[FACTORY] ✅ Loaded and attached: {full_module_path}")

                            except Exception as fallback_error:
                                self.log(
                                    f"[FACTORY][FAIL] Could not dynamically load handler '{handler_name}': {fallback_error}")

                        except Exception as e:
                            self.log(f"[UNIFIED][ERROR] Failed to process {fname}: {e}")
                            continue

            except Exception as loop_error:
                self.log(f"[UNIFIED][LOOP-ERROR] {loop_error}")

            try:
                handler_fn = getattr(self, "packet_listener_post", None)
                if callable(handler_fn):
                    self.packet_listener_post() #used as hook or cron, so any operation that effect the agent_tree for instance stay on same thread

            except Exception as e:
                print(f"[UNIFIED-LISTENER][INFO] self.packet_listener_post() not implemented")

            interruptible_sleep(self, 2)



    def save_directive(self, path: dict, node_tree :dict):
        """
        Encrypt and deliver the directive tree using a structured path dictionary.

        path: {
            "path": base communication path (e.g., /comm/data),
            "address": universal_id (e.g., agent ID),
            "drop": drop zone (e.g., 'directive'),
            "name": filename (e.g., 'agent_tree_master.json')
        }
        """
        try:

            pk1 = self.get_delivery_packet("standard.tree.packet", new=True)

            pk1.set_data(node_tree)

            priv_key=None

            if ENCRYPTION_CONFIG.is_enabled():
               priv_key = ENCRYPTION_CONFIG.get_matrix_private_key()

            ra = self.get_delivery_agent("file.json_file", new=True, priv_key=priv_key)

            ra.set_location({"path": path["path"]}) \
                .set_identifier(path['name']) \
                .set_metadata({"atomic": True}) \
                .set_address([path["address"]]) \
                .set_drop_zone({"drop": path["drop"]}) \
                .set_packet(pk1) \
                .deliver()

            self.log(f"[SAVE] ✅ Encrypted directive delivered to {path['address']}/{path['drop']}/{path['name']}")
            return True

        except Exception as e:
            self.log(f"[BOOT][DUMP-TREE-DELIVERY-ERROR] ❌ {e}")
            return False

    def load_directive(self,path :dict):
        try:

            pub_key=None

            if ENCRYPTION_CONFIG.is_enabled():
                pub_key = ENCRYPTION_CONFIG.get_matrix_public_key()

            pk1 = self.get_delivery_packet("standard.tree.packet", new=True)

            packet = self.get_reception_agent("file.json_file", new=True, pub_key=pub_key) \
                .set_location({"path": path["path"]}) \
                .set_identifier(path["name"]) \
                .set_address(path["address"]) \
                .set_packet(pk1) \
                .set_drop_zone({"drop": path["drop"]}) \
                .receive()

            if packet is None:
                raise ValueError("Failed to receive data from reception agent.")

            data=packet.get_packet()

            return TreeParser.load_tree_direct(data)

        except Exception as e:
            self.log(f"[BOOT][TREE_LOAD_ERROR] {e}")
            return None


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

        #try:
            #with open(full_path, "w") as f:
            #    json.dump(packet, f, indent=2)
        #except Exception as e:
        #    self.log(f"[TRACE][ERROR] Failed to write trace packet {fname}: {e}")

    def _throttled_worker_wrapper(self):
        self.log("[BOOT] Throttled worker wrapper engaged.")
        config_path = os.path.join(self.path_resolution["comm_path_resolved"], "config")
        os.makedirs(config_path, exist_ok=True)
        emit_beacon = self.check_for_thread_poke("poke.worker", 5)
        last_dir_mtime = os.path.getmtime(config_path)

        try:

            pub_key = None

            if ENCRYPTION_CONFIG.is_enabled():
                pub_key = ENCRYPTION_CONFIG.get_matrix_public_key()

            ra = self.get_reception_agent("file.json_file", new=True, pub_key=pub_key)
            ra.set_location({"path": self.path_resolution["comm_path"]}) \
                .set_address([self.command_line_args["universal_id"]]) \
                .set_drop_zone({"drop": "config"})

        except Exception as e:
            self.log(f"[UNIFIED][ERROR] Failed to process: {e}")

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

                        config=None

                        try:

                            current_dir_mtime = os.path.getmtime(config_path)
                            if current_dir_mtime != last_dir_mtime:
                                last_dir_mtime = current_dir_mtime

                                for fname in os.listdir(config_path):
                                    if not fname.endswith(".json"):
                                        continue

                                    #get json packet
                                    pk1 = self.get_delivery_packet("standard.general.json.packet", new=True)

                                    packet = ra.set_identifier(fname) \
                                        .set_packet(pk1) \
                                        .receive()

                                    fpath = os.path.join(config_path, fname)  # get the file's path
                                    os.remove(fpath)

                                    config = packet.get_packet()

                                    if ra.get_error_success() or packet is None:
                                        self.log(f"Failed to receive data from reception agent or error: {ra.get_error_success_msg()}.")

                        except Exception as e:
                            self.log(f"[WORKER]['CONFIG'][ERROR] {e}")
                            e=e

                        if not isinstance(config, dict):
                            config=None
                        else:
                            self.log(f"[WORKER]['CONFIG'] loaded config: {config}")

                        self.log(f"[WORKER] Executing worker cycle...")
                        self.worker(config)

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

    def get_nodes_by_role(self, role: str, scope: str = "child", return_count: int = 0):
        """
        Unified role matcher from both tree and cached service list.

        role: comma-separated roles (e.g., "hive.alert.*, comm")
        scope: "child", "child(1)", "any", or "child(0)"
        return_count: 0 = return all, 1 = first match, 2 = first two, etc.
        """
        try:
            role_list = [r.strip() for r in role.split(",") if r.strip()]
            if not role_list:
                return []

            # Determine depth limit
            depth_limit = None
            if scope.startswith("child("):
                try:
                    depth_limit = int(scope.split("(")[1].split(")")[0])
                except:
                    depth_limit = 1
            elif scope == "child":
                depth_limit = 1
            elif scope == "any" or scope == "child(0)":
                depth_limit = None
            else:
                depth_limit = 1

            matches = []

            nodes = self.get_cached_service_managers()

            seen_uids = set()
            matches = []

            for node in nodes:
                for svc in node.get("config", {}).get("service-manager", []):
                    raw_roles = svc.get("role", [])
                    flat_roles = []
                    for role_entry in raw_roles:
                        if isinstance(role_entry, str):
                            if "," in role_entry:
                                flat_roles.extend(r.strip() for r in role_entry.split(","))
                            else:
                                flat_roles.append(role_entry.strip())

                    for role in flat_roles:
                        for pattern in role_list:
                            if fnmatch.fnmatch(role, pattern):
                                uid = node.get("universal_id")
                                if uid and uid not in seen_uids:
                                    seen_uids.add(uid)
                                    matches.append(node)
                                break

            unique_matches = {}
            for m in matches:
                uid = m.get("universal_id")
                if uid and uid not in unique_matches:
                    unique_matches[uid] = m

            result = list(unique_matches.values())
            return result if return_count <= 0 else result[:return_count]

        except Exception as e:
            self.log(f"[INTEL][ERROR] get_nodes_by_role failed: {e}")
            return []

    def get_cached_service_managers(self):
        if hasattr(self, "_service_manager_services") and self._service_manager_services:
            return self._service_manager_services
        else:
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

        tree_path_resolved = os.path.join(self.path_resolution['comm_path'], self.command_line_args["universal_id"], "directive", "agent_tree.json")

        tree_path = {
            "path": self.path_resolution["comm_path"],
            "address": self.command_line_args["universal_id"],
            "drop": "directive",
            "name": "agent_tree.json"
        }

        while self.running:
            try:
                print(f"[SPAWN] Checking for delegated children of {self.command_line_args['universal_id']}")

                if not os.path.exists(tree_path_resolved):
                    interruptible_sleep(self, 5)
                    continue

                mtime = os.path.getmtime(tree_path_resolved)
                if mtime != last_tree_mtime:

                    tp = self.load_directive(tree_path)
                    self._service_manager_services = getattr(tp, "_service_manager_services", [])

                    if not tp or not hasattr(tp, "root"):
                        self.log("[SPAWN][ERROR] Failed to load directive — invalid tree object.")
                        interruptible_sleep(self, 5)
                        continue

                    tree = tp.root
                    last_tree_mtime = mtime
                    self.log(f"[SPAWN] Tree updated from disk.")

                if not tree:
                    print(f"[SPAWN][ERROR] Could not load tree for {self.command_line_args['universal_id']}")
                    interruptible_sleep(self, 5)
                    continue

                for child_id in tp.get_first_level_child_ids(self.command_line_args["universal_id"]):

                    node = tp.nodes.get(child_id)
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

                    keychain = generate_agent_keypair()
                    keychain["swarm_key"] = self.swarm_key
                    keychain["matrix_pub"] = self.matrix_pub
                    keychain["matrix_priv"]=DUMMY_MATRIX_PRIV
                    keychain["encryption_enabled"]=int(self.encryption_enabled)
                    if node.get("universal_id") == 'matrix':
                        keychain["matrix_priv"] = self.matrix_priv

                    cfg = node.get("config", {})
                    if bool(cfg.get("matrix_secure_verified")) is True:
                        self.logger.log("[TRUST] matrix_secure_verified: TRUE → injecting real Matrix private key.")
                        keychain["matrix_priv"] = self.matrix_priv



                    #TODO: verify if the agent is in memory first, before spawning, if it is, launch a reaper
                    #      wait for reaper to give all clear, removing die cookie to signal

                        # Call new tactical spawn function
                    self.spawn_agent_direct(
                        universal_id=node.get("universal_id"),
                        agent_name=node.get("name"),
                        tree_node=node,
                        keychain=keychain
                    )

            except Exception as e:
                tb = traceback.format_exc()
                print(f"[SPAWN] Exception occurred: {e}")
                print(f"[SPAWN] Full traceback:\n{tb}")

            interruptible_sleep(self, 10)

    def spawn_agent_direct(self, universal_id, agent_name, tree_node, keychain=None):

        spawner = CoreSpawner(
            site_root_path=self.path_resolution["site_root_path"],
            python_site=self.path_resolution["python_site"],
            detected_python=self.path_resolution["python_exec"]
        )

        if keychain and len(keychain)>0:
            spawner.set_keys(keychain)

        comm_file_spec = []
        spawner.ensure_comm_channel(universal_id, comm_file_spec, tree_node.get("filesystem", {}))
        new_uuid, pod_path = spawner.create_runtime(universal_id)

        spawner.set_verbose(self.verbose)

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

    #gives a given agent its agent_tree.json
    def delegate_tree_to_agent(self, universal_id, tree_path):
        try:

            tp = self.load_directive(tree_path)
            if not tp:
                self.log(f"[DELEGATE] Failed to load master tree for {universal_id}")
                return

            subtree = tp.extract_subtree_by_id(universal_id)
            if not subtree:
                self.log(f"[DELEGATE] No subtree found for {universal_id}, sending empty tree.")
                subtree = {}

            # define structured path dict for saving
            path = {
                "path": self.path_resolution["comm_path"],
                "address": universal_id,
                "drop": "directive",
                "name": "agent_tree.json"
            }

            data={"agent_tree": subtree, 'services': tp.get_service_managers(universal_id)}
            self.save_directive(path, data)

            self.log(f"[DELEGATE] Tree delivered to {universal_id}")
        except Exception as e:
            self.log(f"[DELEGATE-ERROR] {e}")

