#Authored by Daniel F MacDonald and ChatGPT aka The Generals
#Gemini, doc-rocking the Swarm to perfection.
import os
import time
import traceback
import threading
import json
import hashlib
import fnmatch
import inspect
import copy
from enum import Enum

from core.class_lib.packet_delivery.utility.crypto_processors.identity import IdentityObject
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
from cryptography.hazmat.primitives import serialization
from core.mixin.ghost_vault import decrypt_vault
from core.utils.trust_log import log_trust_banner
from core.boot_agent_thread_config import get_default_thread_registry
from core.trust_templates.matrix_dummy_priv import DUMMY_MATRIX_PRIV
from core.tree_parser import TreeParser
from core.class_lib.packet_delivery.utility.crypto_processors.football import Football
from core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject

class BootAgent(PacketFactoryMixin, PacketDeliveryFactoryMixin, PacketReceptionFactoryMixin, GhostRiderUltraMixin, IdentityRegistryMixin):
    """The foundational class for all agents in the MatrixSwarm.
    This class provides the core functionality required for an agent to operate
    within the swarm, including secure initialization from a vault, lifecycle
    management through multithreading, and the packet-based communication system.
    All specific agents must inherit from BootAgent.
    """
    if __name__ == "__main__":

        raise RuntimeError("Direct execution of agents is forbidden. Only Matrix may be launched via bootloader.")

    def __init__(self):
        """Initializes the agent by securely decrypting its configuration.
        This method is the entry point for a newly spawned agent. It reads the
        SYMKEY and VAULTFILE from environment variables, decrypts the payload,
        and uses it to set up all core attributes, including security keys,
        path resolutions, and cryptographic handlers ("Footballs") for
        communication.

        Attributes:
            path_resolution (dict): A dictionary of all essential filesystem paths.
            command_line_args (dict): Arguments passed at spawn time, like universal_id.
            tree_node (dict): The agent's specific node from the master directive.
            swarm_key (str): The global AES key used for general packet encryption.
            private_key (str): The agent's personal AES key.
            matrix_pub (str): The PEM-encoded public key of the root Matrix agent.
            matrix_priv (str): The private key of the Matrix agent (often a dummy key).
            public_key_obj: The agent's own public key as a cryptography object.
            private_key_obj: The agent's own private key as a cryptography object.
            logger (Logger): An encrypted logger instance for this agent.
            running (bool): A flag that controls the main loops of the agent's threads.
            _pass_football (Football): A pre-configured crypto handler for sending packets.
            _catch_football (Football): A pre-configured crypto handler for receiving packets.
        """
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

        #used by the swarm to encrypt packets
        self.swarm_key = payload.get("swarm_key")  #swarm AES Key
        #this is for Matrix only and maybe a bogus key, only the real Matrix gets this and her Sentinels
        self.private_key = payload.get("private_key") #private AES Key

        #these 2 guys are aux and are created by the parent
        self.matrix_pub = payload.get("matrix_pub")
        self.matrix_priv = payload.get("matrix_priv")  # Fallback already handled by decrypt_vault()

        #these are the same 2 guys that have been converted in the vault
        self.public_key_obj = payload["public_key_obj"]
        self.private_key_obj = payload["private_key_obj"]
        self.pub_fingerprint = payload["pub_fingerprint"]
        self.secure_keys = payload.get("secure_keys", {})
        self.cached_pem = payload.get("cached_pem", {})
        #hold Matrix credentials, encase of her going down
        self.security_box = payload.get("security_box", {})

        config = EncryptionConfig()

        self.logger = Logger(self.path_resolution["comm_path_resolved"], "logs", "agent.log")

        self.encryption_enabled=bool(payload.get("encryption_enabled",0))
        if self.encryption_enabled:
            config.set_swarm_key(self.swarm_key)
            config.set_private_key(self.private_key)
            config.set_enabled(True)
            self.logger.set_encryption_key(self.swarm_key)

        # Optional fingerprint of Matrix public key
        try:
            self.matrix_fingerprint = hashlib.sha256(self.matrix_pub.encode()).hexdigest()[:12]
        except Exception as e:
            self.log(f"[BOOT] matrix_pub is missing. Trust cannot be verified.", error=e, block="optional_fingerprint")


        # Convert to objects

        try:
            self.matrix_pub_obj = serialization.load_pem_public_key(self.matrix_pub.encode())
        except Exception as e:
            self.matrix_pub_obj = None
            self.log(f"[BOOT] matrix_pub is missing. Trust cannot be verified.", error=e, block="serialize_public_key")
            exit()

        try:
            self.matrix_priv_obj = serialization.load_pem_private_key(self.matrix_priv.encode(), password=None)
        except Exception as e:
            self.matrix_priv_obj = None
            self.log(f"[TRUST][WARN] Matrix private key invalid or placeholder", error=e, block="serialize_private_key")
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
            private_key=self.private_key
        )

        #this option will be pulled from the command line as debug
        #all packets all directives, using the self.swarm_key
        self.packet_encryption=True

        self.boot_time = time.time()
        self.running = False
        self.subordinates = []
        self.thread_registry = get_default_thread_registry()

        if self.encryption_enabled:
            config.set_pub(self.public_key_obj)
            config.set_priv(self.private_key_obj)
            config.set_matrix_pub(self.matrix_pub_obj)
            config.set_matrix_priv(self.matrix_priv_obj)

        self.verbose = bool(self.command_line_args.get('verbose',0))
        self._loaded_tree_nodes={}
        self._service_manager_services = {}

        self.running = False

        '''
        fb.add_identity(matrix_node['vault'],
                identity_name="agent_owner",    #owner identity
                verify_universal_id=True,       #make sure the universal_id of the agent is the same as the one in the identity
                universal_id="matrix",          #compare universal_id to the one stored in the identity, sanity check
                is_payload_identity=True,         #yes, this payload is an identity, if identity embedding is turned on this will be the identity that will be embeded, since it will be the identity of the user sending the packet
                sig_verifier_pubkey=matrix_pub,   #this pubkey is used to verify the identity, always Matrix's pubkey
                is_pubkey_for_encryption=False,    #if you turn on asymmetric encryption the pubkey in the identity will encrypt, check payload size
                is_privkey_for_signing=True,       #use the privkey that belongs to the identity pubkey to sign the whole subpacket
                )
        '''

        #cache the identity, no need to do the calculations every instantiation
        #basic identity template to send a packet
        self._pass_football= Football()
        self._pass_football.set_identity_sig_verifier_pubkey(self.matrix_pub)  # this is used to verify the agent's own identity, sanity check
        self._pass_football.add_identity(self.tree_node["vault"],
                                    identity_name="agent_owner",
                                    universal_id=self.command_line_args.get("universal_id"), #verify the agents own universal_id,
                                    is_payload_identity=True,
                                    is_privkey_for_signing=True
                                    )
        self._pass_football.set_pubkey_verifier(self.matrix_pub) #Matrix pubkey to verify the inner-identity
        self._pass_football.set_identity_base_path(self.path_resolution['comm_path'])
        #self._pass_football.set_aes_key(self.swarm_key)
        #self._pass_football.set_aes_encryption_pubkey() #used for sending the aes encryption key using targets, pubkey
        #self._pass_football.set_aes_encryption_privkey() #used by the receiving target to decrypt the aes key and decrypt the payload


        # basic identity template to receive a packet
        self._catch_football = Football()
        self._catch_football.set_identity_sig_verifier_pubkey(self.matrix_pub)  # this is used to verify the agent's own identity, sanity check
        self._catch_football.add_identity(
                                         self.tree_node["vault"],
                                         identity_name="agent_owner",
                                         universal_id=self.command_line_args.get("universal_id"),
                                         )
        self._catch_football.set_pubkey_verifier(self.matrix_pub)  # Matrix pubkey to verify the inner-identity
        self._catch_football.set_aes_encryption_privkey(self.secure_keys.get("priv"))  #used by the receiving agent to decrypt the aes key that wa
        # s encrypted with the paired pubkey, then using the aes key to decrypt the payload
        self._catch_football.set_identity_base_path(self.path_resolution['comm_path'])
    class FootballType(Enum):
        PASS = 1
        CATCH = 2

    def get_football(self, type: FootballType = FootballType.PASS ):

        try:
            if type == self.FootballType.CATCH:
                fb = copy.deepcopy(self._catch_football)
            elif type == self.FootballType.PASS:
                fb = copy.deepcopy(self._pass_football)
            else:
                raise ValueError("Unknown football type or type not provided")

        except Exception as e:
            self.log(error=e, block="main_try")

        return fb

    def log(self, msg="", error: Exception = None, block=None, include_stack=True, level="INFO", custom_tail=None):
        """A custom logging method that automatically injects agent context.

        This wrapper around the standard logger automatically prepends a prefix
        to every log message, including the agent's name, the calling method's
        name, and the line number. This provides rich, contextual logging
        across the entire swarm with zero configuration.

        Args:
            msg (str): The message to log.
            error (Exception, optional): An exception object to log.
            block (str, optional): An optional string to add a custom block name.
            level (str, optional): The log level (e.g., "INFO", "ERROR").
        """
        try:

            if custom_tail:

                agent = self.command_line_args.get("agent_name", "UNKNOWN").upper()

                prefix = f"[{agent}]{custom_tail}"

            else:

                frame = inspect.currentframe()
                outer_frames = inspect.getouterframes(frame)

                if len(outer_frames) > 1:
                    outer = outer_frames[1]
                else:
                    outer = outer_frames[0]

                method_name = outer.function.upper()
                lineno = outer.lineno

                if not isinstance(error, (BaseException, type(None))):
                    raise TypeError(f"'error' must be an Exception, not {type(error).__name__}")

                agent = self.command_line_args.get("agent_name", "UNKNOWN").upper()

                prefix = f"[{agent}][{method_name}][L{lineno}]"

            if block:
                prefix += f"[{block.upper()}]"

            if not msg and error is None:
                return  # no payload to log

            if error:
                err_str = str(error)
                self.logger.log(f"{prefix} {msg} : {err_str}", level=level)
                if include_stack:
                    self.logger.log(traceback.format_exc(), level="DEBUG")
            else:
                self.logger.log(f"{prefix} {msg}", level=level)

        except Exception as fallback:
            print(f"[LOG-FAIL] Logging system failure: {fallback}")

    def send_message(self, message):
        self.log(f"[SEND] {json.dumps(message)}")

        # sends a heartbeat to comm/{universal_id}/hello.moto of self

    def heartbeat(self):
        """Periodically writes a timestamp to a file to signal liveness.
        This method runs in a continuous loop in its own thread. It creates a
        `poke.heartbeat` file in the agent's `/hello.moto` directory and
        updates it with the current timestamp every 10 seconds. Other agents,
        like Sentinels, monitor this file to determine if the agent is still
        alive.
        """
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
                    f"[INFO]core.agent.py: enforce_singleton: {self.command_line_args['universal_id']} die cookie ingested, going down easy...")

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
        self.log("Starting factory injection from 'factories' block only.")

        config = self.tree_node.get("config", {})
        factories = config.get("factories", {})

        self.log(f"Found factories: {list(factories.keys())}")

        for dotted_path, factory_config in factories.items():
            if not isinstance(dotted_path, str) or "." not in dotted_path:
                self.log(f"Invalid factory path: {dotted_path}")
                continue

            try:
                full_module_path = f"agent.{self.command_line_args['agent_name']}.factory.{dotted_path}"
                self.log(f"Attempting: {full_module_path}")
                mod = __import__(full_module_path, fromlist=["attach"])
                mod.attach(self, factory_config)
                self.log(f"Loaded: {full_module_path}")
            except Exception as e:
                self.log(f"{dotted_path} → {e}", error=e, block="main-try")

    def is_worker_overridden(self):
        return self.__class__.worker != BootAgent.worker

    def boot(self):
        """Starts the agent's main operational threads.

       This is the primary entry point to activate the agent after it has been
       initialized. It sets the agent's status to 'running' and launches all
       essential background threads for heartbeat, singleton enforcement,
       inter-agent communication, and the main worker process.
       """
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
            self.log(error=e, block="main-try")

    """The main operational loop for the agent, intended to be overridden.
    This method is called repeatedly by the _throttled_worker_wrapper.
    Developers should override this method in their own agent classes to
    define the agent's primary logic and tasks. The base implementation
    simply logs a message and sleeps.

    Args:
        config (dict, optional): A dictionary containing the agent's
            most recent configuration, loaded dynamically from the
            /config directory. Defaults to None.
        identity (IdentityObject, optional): An object containing the
            verified identity of the sender if the worker is triggered
            by a packet. Defaults to None.
    """
    def worker(self, config:dict = None, identity:IdentityObject=None):
        self.log("[BOOT] Default worker loop running. Override me.")
        while self.running:
            interruptible_sleep(self, 5)
    def pre_boot(self):
        """A one-time setup hook called before the main threads start.
        This method is intended to be overridden by child agent classes.
        It runs once during the boot() sequence, after initialization but
        before the heartbeat, worker, or listener threads are launched. It is
        ideal for initial health checks or setup that doesn't require threads.
        """
        self.log("[BOOT] Default pre_boot (override me if needed)")

    def post_boot(self):
        """A one-time setup hook called after the main threads have started.
        This method is intended to be overridden by child agent classes.
        It runs once at the end of the boot() sequence after all core
        background threads are active. It is ideal for tasks that should
        run once the agent is fully operational.
        """
        self.log("[BOOT] Default post_boot (override me if needed)")

    def packet_listener(self):
        """Monitors the incoming directory for new command packets.
        This method is the core of inter-agent communication. Running in a
        continuous loop, it watches the agent's `/incoming` directory for new
        `.json` files. When a file appears, it uses a ReceptionAgent to
        securely decrypt and validate the packet. It then dynamically calls the
        appropriate handler method within the agent to process the command.
        After processing, the packet file is deleted.
        """
        self.log("Monitoring incoming packets...")
        incoming_path = os.path.join(self.path_resolution["comm_path_resolved"], "incoming")
        os.makedirs(incoming_path, exist_ok=True)
        emit_beacon = self.check_for_thread_poke("packet_listener", 5)
        last_dir_mtime = os.path.getmtime(incoming_path)
        #TOP TRY
        try:

            football = self.get_football(type=self.FootballType.CATCH)
            ra = self.get_reception_agent("file.json_file", new=True, football=football)
            ra.set_location({"path": self.path_resolution["comm_path"]}) \
                .set_address([self.command_line_args["universal_id"]]) \
                .set_drop_zone({"drop": "incoming"})

        except Exception as e:
            self.log(error=e, block="top_try")

        while self.running:

            #Main Try
            try:

                emit_beacon()

                current_dir_mtime = os.path.getmtime(incoming_path)
                if current_dir_mtime != last_dir_mtime:
                    last_dir_mtime = current_dir_mtime

                    for fname in os.listdir(incoming_path):
                        #dynamic config packet
                        try:
                            if not fname.endswith(".json"):
                                continue

                            pk = self.get_delivery_packet("standard.command.packet", new=True)
                            pk2 = self.get_delivery_packet("standard.general.json.packet", new=True)
                            pk.set_packet(pk2)

                            packet = ra.set_identifier(fname) \
                                       .set_packet(pk) \
                                       .receive()

                            fpath = os.path.join(incoming_path, fname)  # get the file's path

                            try:
                                os.remove(fpath)
                                identity=ra.get_identity()
                            except Exception as e:
                                identity=None

                            try:
                                pk = packet.get_packet()
                            except Exception as e:
                                self.log(f"Failed to process {fname} :{pk}", error=e, block="dynamic_config_packet")
                                pk={}

                            if ra.get_error_success() or packet is None:
                                pk={}
                                self.log(f"Failed to receive data from reception agent or error: {ra.get_error_success_msg()}.")

                            #self.log(f"processing packet: {fname}")

                            handler = pk.get("handler")
                            if not handler:
                                self.log(f"[UNIFIED][SKIP] No 'call' in: {fname} packet: {pk}")
                                continue

                            handler_name = pk.get("handler")
                            content = pk.get("content", {})


                            # 1. Check if the class has a direct method with this name
                            handler_fn = getattr(self, handler_name, None)
                            #factory handler check
                            if callable(handler_fn):
                                try:
                                    handler_fn(content, pk, identity)
                                    self.log(f"[UNIFIED] ✅ Executed handler: {handler_name}")
                                    continue
                                except Exception as e:
                                    self.log(f"[UNIFIED][ERROR] Handler '{handler_name}' failed: {e}")

                            # 2. Fallback: Try to dynamically load a factory module
                            self.log(f"No direct handler '{handler_name}', attempting factory load...")

                            #dynamic module loader
                            try:
                                # Clean up handler name (e.g. strip namespaces)
                                handler_id = handler_name.split(".")[-1]  # e.g. cmd_example
                                full_module_path = f"agent.{self.command_line_args['agent_name']}.factory.{handler_id}"

                                self.log(f"Attempting: {full_module_path}")

                                mod = __import__(full_module_path, fromlist=["attach"])
                                mod.attach(self, {"packet": pk, "content": content, "identity": identity})

                                self.log(f"✅ Loaded and attached: {full_module_path}")

                            except Exception as fallback_error:
                                self.log( f"Could not dynamically load handler '{handler_name}': {fallback_error}", error=fallback_error, block="dynamic_config_packet")

                        except Exception as e:
                            self.log(f"Failed to process {fname}", error=e)
                            if fpath and os.path.isfile(fpath):
                                os.remove(fpath)
                            continue

            except Exception as loop_error:

                self.log("Error in loop", error=loop_error, block="main_try")

            #packet_listener_post call
            try:
                handler_fn = getattr(self, "packet_listener_post", None)
                if callable(handler_fn):
                    self.packet_listener_post() #used as hook or cron, so any operation that effects the agent_tree for instance stay on same thread

            except Exception as e:
                self.log(error=e, block="packet_listener_post")

            interruptible_sleep(self, 2)


    def save_directive(self, path: dict, node_tree :dict, football:Football):
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

            ra = self.get_delivery_agent("file.json_file", new=True, football=football)

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
            self.log(f"[BOOT][DUMP-TREE-DELIVERY-ERROR] ❌", error=e, block="main_try")
            return False

    def load_directive(self, path :dict, football:Football):
        try:

            if ENCRYPTION_CONFIG.is_enabled():
                football.set_allowed_sender_ids(["matrix"])

            pk1 = self.get_delivery_packet("standard.tree.packet", new=True)

            packet = self.get_reception_agent("file.json_file", football=football) \
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
            self.log(f"[BOOT][DUMP-TREE-DELIVERY-ERROR] ❌", error=e, block="main_try")
            return TreeParser.load_tree_direct({})

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
        """A wrapper that manages the execution of the main worker() method.

        This wrapper provides two key features:
        1.  Dynamic Throttling: It monitors the system's load average and
            introduces a delay between worker() loop executions if the load
            is too high, preventing the swarm from overloading the host system.
        2.  Real-Time Configuration: It monitors the agent's /config directory
            for new .json files. If a new config file is dropped, it is
            securely loaded and passed into the next execution of the worker()
            method, allowing for on-the-fly configuration changes.
        """
        self.log("Throttled worker wrapper engaged.")
        config_path = os.path.join(self.path_resolution["comm_path_resolved"], "config")
        os.makedirs(config_path, exist_ok=True)
        fpath=None
        identity=None
        emit_beacon = self.check_for_thread_poke("worker", 5)
        last_dir_mtime = os.path.getmtime(config_path)
        last_worker_cycle_execution = 0
        try:



            football = self.get_football( type = self.FootballType.CATCH)
            ra = self.get_reception_agent("file.json_file", new=True, football=football)
            ra.set_location({"path": self.path_resolution["comm_path"]}) \
                .set_address([self.command_line_args["universal_id"]]) \
                .set_drop_zone({"drop": "config"})


        except Exception as e:
            self.log(f"Failed to process", error=e, block="main_try")

        # 🔹 Optional pre-hook (called ONCE before loop)
        if hasattr(self, "worker_pre"):
            try:
                self.worker_pre()
                self.resolve_factory_injections()
            except Exception as e:
                self.log(error=e)

        while self.running:

            if getattr(self, "can_proceed", True):

                try:

                    self.can_proceed = False

                    if self.is_worker_overridden():

                        config={}
                        _config = {} #temp config
                        try:

                            #ON EXECUTION, THIS WILL SCOOP UP ALL THE CONFIG PACKETS
                            #BUT  ONLY SEND THE LAST ONE TO THE WORKER METHOD
                            #AND DELETE THE REST OF THE PACKETS
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

                                    _config = packet.get_packet()

                                    if ra.get_error_success() or packet is None:
                                        self.log(f"Failed to receive data from reception agent or error: {ra.get_error_success_msg()}.")

                                    #self.log(f"config: path: {fpath} {config}")

                                    os.remove(fpath)

                                    identity = ra.get_identity()

                                    if isinstance(_config, dict):
                                        config = _config.copy()

                        except Exception as e:
                            if fpath and os.path.isfile(fpath):
                                os.remove(fpath)
                            self.log(f"config {config}", error=e)

                        now = time.time()
                        if (last_worker_cycle_execution + 30) < now:
                            last_worker_cycle_execution = now
                            self.log(f"Executing worker cycle...")

                        #REMEMBER THIS ISN'T ENTERED LIKE PACKET_LISTENER
                        #THERE MAY BE A LARGE TIMEOUT IN WORKER
                        self.worker(config, identity)

                    else:
                        if not hasattr(self, "_worker_skip_logged"):
                            self.log("No worker() override detected — skipping worker loop.")
                            self._worker_skip_logged = True

                    emit_beacon()
                except Exception as e:
                    self.emit_dead_poke("worker", str(e))
                    self.log(error=e, block="main_try")

            else:

                time.sleep(0.05)

        # 🔹 Optional post-hook (called ONCE after loop exits)
        if hasattr(self, "worker_post"):
            try:
                self.worker_post()
            except Exception as e:
                self.log(error=e)

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
            last_throttle_cycle_execution=False
            greatest_load=0
            while self.running:
                try:
                    load_avg = os.getloadavg()[0]
                    scale = min(1.0, (load_avg - max_load) / max_load) if load_avg > max_load else 0
                    delay = int(min_delay + scale * (max_delay - min_delay))
                    if scale > 0:

                        #avoid all the throttle print statements, uses outer else
                        if not last_throttle_cycle_execution:
                            last_throttle_cycle_execution = True
                            self.log(f"[THROTTLE_STARTED] Load: {load_avg:.2f} → delay: {delay}s")

                        if load_avg>greatest_load:
                            greatest_load = load_avg

                    else:
                        if last_throttle_cycle_execution:
                            last_throttle_cycle_execution = False
                            self.log(f"[THROTTLE_ENDED] Highest Load: {greatest_load:.2f}")
                            greatest_load = 0

                    self.can_proceed = True
                    time.sleep(delay)
                except Exception as e:
                    self.log(error=e)
                    time.sleep(min_delay)

        self.can_proceed = False
        threading.Thread(target=dynamic_throttle_loop, daemon=True).start()

    def get_nodes_by_role(self, role: str, scope: str = "child", return_count: int = 0):
        """Finds other agents in the swarm based on their advertised roles.

        This method is the core of the swarm's service discovery system. It
        searches the agent tree for any node whose 'service-manager' config
        block contains a matching role. This allows agents to find service
        providers (e.g., alert relays) without needing to know their specific
        universal_id.

        Args:
            role (str): The role to search for. Supports wildcards (e.g., "comm.security.*").
            scope (str): The search scope (e.g., "child", "any").
            return_count (int): The maximum number of nodes to return. 0 for all.

        Returns:
            list: A list of agent node dictionaries that match the requested role.
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

    def get_nodes_by_subscription(self, topic: str, scope: str = "child", return_count: int = 0):
        """Monitors and manages the lifecycle of this agent's direct children.

        Running in its own thread, this method periodically checks the agent's
        directive for any defined children. For each child, it checks the age
        of its heartbeat file. If the heartbeat is stale (older than the
        timeout), this method assumes the child agent has crashed and will
        automatically re-spawn it using the spawn_agent_direct() method. This
        is the primary mechanism for the swarm's self-healing capability.
        """
        try:
            topic = topic.strip()
            if not topic:
                return []

            depth_limit = None
            if scope.startswith("child("):
                try:
                    depth_limit = int(scope.split("(")[1].split(")")[0])
                except:
                    depth_limit = 1
            elif scope == "child":
                depth_limit = 1
            elif scope in ("any", "child(0)"):
                depth_limit = None
            else:
                depth_limit = 1

            nodes = self.get_cached_service_managers()

            seen_uids = set()
            matches = []

            for node in nodes:
                for svc in node.get("config", {}).get("service-manager", []):
                    subscriptions = svc.get("subscribe", [])
                    if isinstance(subscriptions, str):
                        subscriptions = [subscriptions]
                    for sub in subscriptions:
                        if sub.strip() == topic and node.get("universal_id") not in seen_uids:
                            seen_uids.add(node.get("universal_id"))
                            matches.append(node)
                            break  # one match per node is enough

            return matches if return_count <= 0 else matches[:return_count]

        except Exception as e:
            self.log(f"[INTEL][ERROR] get_nodes_by_subscription failed: {e}")
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

                    football = self.get_football(type=self.FootballType.CATCH)
                    tp = self.load_directive(tree_path, football=football)
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

                    # Skip deleted nodes
                    if node.get("deleted", False) is True:
                        # self.log(f"[SPAWN-BLOCKED] {node.get('universal_id')} is marked deleted.")
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

                    #TODO: verify if the agent is in memory first, before spawning, if it is, launch a reaper
                    #      wait for reaper to give all clear, removing die cookie to signal

                        # Call new tactical spawn function
                    self.spawn_agent_direct(
                        universal_id=node.get("universal_id"),
                        agent_name=node.get("name"),
                        tree_node=node,
                        keychain=self.ring_keychain(node)
                    )

            except Exception as e:
                self.log(error=e, block="main_try")

            interruptible_sleep(self, 10)

    def ring_keychain(self, node:dict)->dict:

        try:
            if not isinstance(node, dict):
                return {}

            keychain={}
            keychain["priv"] = node.get("vault",{}).get("priv",{})
            keychain["pub"] = node.get("vault",{}).get("identity",{}).get('pub',{})
            keychain["swarm_key"] = self.swarm_key
            keychain['private_key'] = node.get("vault",{}).get("private_key")
            keychain["matrix_pub"] = self.matrix_pub
            keychain["matrix_priv"]=DUMMY_MATRIX_PRIV
            keychain["encryption_enabled"]=int(self.encryption_enabled)
            keychain["security_box"] = self.security_box.copy()
            #Matrix is running, and currently spawning
            if node.get("universal_id") == 'matrix':
                keychain["matrix_priv"] = self.matrix_priv
                keychain["private_key"] = self.private_key

            cfg = node.get("config", {})
            #these items will be returned to Matrix encase of her early demise
            if bool(cfg.get("matrix_secure_verified")) and len(keychain["security_box"])==0:
                self.log("[TRUST] matrix_secure_verified: TRUE → injecting real Matrix private key.")
                keychain["security_box"]["encryption_enabled"] = int(self.encryption_enabled)
                keychain["security_box"]["matrix_priv"] = self.matrix_priv
                keychain["security_box"]["matrix_pub"] = self.matrix_pub
                #keychain["security_box"]["priv"] = self.secure_keys['priv'] in tree_node
                #keychain["security_box"]["pub"] = self.secure_keys['pub']   in tree_node
                #keychain["security_box"]["private_key"] = self.private_key   in tree_node
                keychain["security_box"]["swarm_key"] = self.swarm_key
                keychain["security_box"]["node"] = self.tree_node.copy()

            return keychain

        except Exception as e:
            self.log(error=e, block="main_try")

        return {}

    def spawn_agent_direct(self, universal_id, agent_name, tree_node, keychain=None):

        try:

            if tree_node.get("deleted", False):
                self.log(f"[SPAWN-ERROR] Attempted to spawn deleted agent {universal_id}. Blocking.")
                return

            spawner = CoreSpawner(
                site_root_path=self.path_resolution["site_root_path"],
                python_site=self.path_resolution["python_site"],
                detected_python=self.path_resolution["python_exec"]
            )

            if keychain and len(keychain) > 0:
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
                universe_id=self.command_line_args.get("universe")
            )

            if result is None:
                self.log(f"[MATRIX][KILL] ERROR: Failed to spawn agent {universal_id}.")
                return

            return result

        except Exception as e:
            self.log(error=e, block="main_try")