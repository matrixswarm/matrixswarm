# At the top of your script
import sys
import os
import site
import hashlib


# Add the directory containing this script to the PYTHONPATH
current_directory = os.path.dirname(os.path.abspath(__file__))  # Directory of the current script
if current_directory not in sys.path:
    sys.path.insert(0, current_directory)

import json
import uuid
import shutil
import subprocess
import traceback
from datetime import datetime
from class_lib.file_system.file_system_builder import FileSystemBuilder
from path_manager import PathManager
from core.class_lib.logging.logger import Logger
from core.mixin.core_spawn_secure import CoreSpawnerSecureMixin
from core.mixin.ghost_vault import build_encrypted_spawn_env, generate_agent_keypair
from cryptography.hazmat.primitives import serialization


class CoreSpawner(CoreSpawnerSecureMixin):
    def __init__(self, path_manager=None, site_root_path='/site/your_site_fallback_path', python_site=None, detected_python=None):
        super().__init__()

        pm = path_manager or PathManager(use_session_root=True, site_root_path=site_root_path)

        self.verbose=False

        self.python_site=python_site
        self.python_exec= detected_python

        self.default_comm_file_spec = [
            {"name": "hello.moto", "type": "d", "content": None},
            {"name": "payload", "type": "d", "content": None},
            {"name": "incoming", "type": "d", "content": None},
            {"name": "queue", "type": "d", "content": None},
            {"name": "stack", "type": "d", "content": None, "meta": "Long - term mission chaining"},
            {"name": "replies", "type": "d", "content": None, "meta": "stack / Long - term mission chaining"},
            {"name": "broadcast", "type": "d", "content": None, "meta": "Shared folder for swarms with listeners"},
        ]

        self.root_path = pm.get_path("root")
        self.comm_path = pm.get_path("comm")
        self.pod_path = pm.get_path("pod")
        self.agent_path = pm.get_path("agent")
        self.site_root_path = pm.get_path("site_root_path")

        os.makedirs(self.comm_path, exist_ok=True)

        os.makedirs(self.pod_path, exist_ok=True)


    def set_verbose(self, verbose):

        self.verbose = bool(verbose)

    def get_path(self, prefix_dir=None, variable_name_dir=None, postfix_dir=None):

        root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
        path = root_path

        if prefix_dir == "comm":
            path = os.path.join(path, "matrixline")
        elif prefix_dir == "pod":
            path = os.path.join(path, "pod")

        if variable_name_dir:
            path = os.path.join(path, variable_name_dir)

        if postfix_dir:
            path = os.path.join(path, postfix_dir)

        return path

    def reset_hard(self):

        #NEED TO WAIT UNTIL ALL PROCESSES HAVE COMPLETED
        for root in [self.comm_path, self.pod_path]:
            for folder in os.listdir(root):
                folder_path = os.path.join(root, folder)
                if os.path.isdir(folder_path):
                    shutil.rmtree(folder_path)

        print("[SPAWNER] Hard reset complete.")

    def verify_soft(self):
        for root in [self.comm_path, self.pod_path]:
            os.makedirs(root, exist_ok=True)
            print(f"[SPAWNER] Verified structure: {root}")

    def ensure_comm_channel(self, universal_id, file_spec, agent_directive=None):

        base = os.path.join(self.comm_path, universal_id)

        os.makedirs(base, exist_ok=True)

        print('comm_channel creation: start')

        # Always process the default file_spec
        fsb = FileSystemBuilder()
        fsb.process_selection(base, self.default_comm_file_spec)

        if self.default_comm_file_spec:
            fs_node = {"folders": self.default_comm_file_spec}
            print(f"[DEBUG] Processing default folders spec: {fs_node}")

            folders = fs_node.get("folders", [])
            if folders:
                print(f"[FS-BUILDER] Merging folders from directive for {universal_id}")
                fsb.process_selection(base, folders)

            files = fs_node.get("files", {})
            for name, content in files.items():
                item = {
                    "name": name,
                    "type": "f",
                    "content": content
                }
                fsb.process_item(base, item)

        # process any special requirements
        # If agent_directive contains additional filesystem specs
        fsb = FileSystemBuilder()
        fsb.process_selection(base, file_spec)
        if agent_directive:
            fs_node = agent_directive if isinstance(agent_directive, dict) and "folders" in agent_directive else {}
            print(f"[DEBUG] Processing filesystem spec: {fs_node}")

            folders = fs_node.get("folders", [])
            if folders:
                print(f"[FS-BUILDER] Merging folders from directive for {universal_id}")
                fsb.process_selection(base, folders)

            files = fs_node.get("files", {})
            for name, content in files.items():
                item = {
                    "name": name,
                    "type": "f",
                    "content": content
                }
                fsb.process_item(base, item)

        print('comm_channel creation: end')


        return base

    def create_runtime(self, universal_id):
        new_uuid = f"{str(uuid.uuid4())}"
        pod_path = os.path.join(self.pod_path, new_uuid)
        os.makedirs(pod_path, exist_ok=True)
        return new_uuid, pod_path

    def destroy_runtime(self, uuid):
        target = os.path.join(self.pod_path, uuid)
        if os.path.exists(target):
            shutil.rmtree(target)
            print(f"[SPAWNER] Destroyed runtime pod: {uuid}")
            return True
        return False

    #returns the boot file, that contains permenint_id
    def get_boot_log(self, path):

        good = False
        content = None

        # Path to the file in the current directory
        path = os.path.join(path, 'boot.json')

        # get the boot file that is json to get the permenant_id
        try:
            with open(path, "r") as f:
                content = json.loads(f.read())
                good = True
        except FileNotFoundError:
            good = False

        return good, content

    def spawn_agent(self, spawn_uuid, agent_name, universal_id, spawner, tree_node=None, universe_id=None):

        try:

            logger = Logger(os.path.join(self.comm_path, universal_id))

            with open("/matrix/spawn.log", "a") as f:
                f.write(f"{datetime.now().isoformat()} :: {universal_id} → {agent_name}\n")

            logger = Logger(os.path.join(self.comm_path, universal_id))
            spawn_path = os.path.join(self.pod_path, spawn_uuid)
            os.makedirs(spawn_path, exist_ok=True)

            base_name = agent_name.split("_bp_")[0] if "_bp_" in agent_name else agent_name
            source_path = os.path.join(self.agent_path, base_name, f"{base_name}.py")

            path_dict = {
                "root_path": self.root_path,
                "pod_path": self.pod_path,
                "comm_path": self.comm_path,
                "agent_path": self.agent_path,
                "incoming_path_template": os.path.join(self.comm_path, "$universal_id", "incoming"),
                "comm_path_resolved": os.path.join(self.comm_path, universal_id),
                "session_path": os.path.dirname(self.pod_path.rstrip("/"))
            }


            if "_bp_" in agent_name:
                base_name = agent_name.split("_bp_")[0]
                session_path = path_dict["session_path"]

                paths = [
                    os.path.join(session_path, "boot_payload", agent_name, f"{agent_name}.py"),
                    os.path.join(session_path, "boot_payload", base_name, f"{base_name}.py"),
                    os.path.join(self.root_path, "boot_payload", agent_name, f"{agent_name}.py"),
                    os.path.join(self.root_path, "boot_payload", base_name, f"{base_name}.py"),
                    os.path.join(self.agent_path, base_name, f"{base_name}.py")  # ultimate fallback
                ]

                for p in paths:
                    logger.log(f"[SPAWN-DEBUG] Boot check path: {p}")

                for path in paths:
                    if os.path.exists(path):
                        source_path = path
                        logger.log(f"[SPAWN] ✅ Loaded agent: {agent_name} from: {source_path}")
                        break


            run_path = os.path.join(spawn_path, "run")
            vault_path = os.path.join(spawn_path, "vault")

            if not source_path or not os.path.exists(source_path):
                logger.log(f"[SPAWN-ERROR] Source path not resolved or file missing. Cannot boot agent: {agent_name}")
                return

            #when the process is spawned it has no way to find the root and the lib path
            #so prepend it with these facts

            tree_node_blob = ""
            if tree_node:
                try:
                    tree_node_blob = f"tree_node = {repr(tree_node)}\n"
                except Exception as e:
                    print(f"[SPAWN-ERROR] Could not encode tree_node for {universal_id}: {e}")

            #data = inject_spawn_landing_zone(file_content, path_dict, cmd_args, tree_node)

            with open(source_path, "r") as f:
                file_content = f.read()

            with open(run_path, "w") as f:
                f.write(file_content)



            timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")

            #GO TIME
            logger.log(f"[SPAWN-MGR] Spawning: {universal_id} agent name {agent_name} from: {source_path}")
            print(f"[SPAWN-MGR] Spawning: {universal_id} agent name {agent_name} from: {source_path}")

            # === CODEX ENTRY ===
            codex_dir = os.path.join(self.comm_path, "matrix", "codex", "agents")
            os.makedirs(codex_dir, exist_ok=True)

            codex_entry = {
                "universal_id": universal_id,
                "title": agent_name.replace("_", " ").title(),
                "summary": f"Spawned by {spawner} on {timestamp}.",
                "timestamp": timestamp
            }

            try:
                with open(os.path.join(codex_dir, f"{universal_id}.json"), "w") as codex_file:
                    json.dump(codex_entry, codex_file, indent=2)
                logger.log(f"[CODEX] Entry written for {universal_id}")
            except Exception as e:
                logger.log(f"[CODEX][ERROR] Failed to write entry for {universal_id}: {e}")

            cmd = [
                self.python_exec or "python3",
                run_path,
                "--job", f"{universe_id}:{spawner}:{universal_id}:{agent_name}",
                "--ts", timestamp
            ]

            if self.verbose:
                stdout = None
                stderr = None
                stdin = None
            else:
                stdout = subprocess.DEVNULL
                stderr = subprocess.DEVNULL
                stdin = subprocess.DEVNULL

            if not tree_node or "secure_keys" not in tree_node:
                raise RuntimeError(f"[SPAWN] secure_keys missing in tree_node for {universal_id}")

            payload = {
                "path_resolution": {
                    "root_path": self.root_path,
                    "pod_path": self.pod_path,
                    "comm_path": self.comm_path,
                    "agent_path": self.agent_path,
                    "incoming_path_template": os.path.join(self.comm_path, "$universal_id", "incoming"),
                    "comm_path_resolved": os.path.join(self.comm_path, universal_id),
                    "pod_path_resolved": os.path.join(self.pod_path, spawn_uuid),
                    "site_root_path": self.site_root_path,
                    "python_site": self.python_site,
                    "python_exec": self.python_exec or "python3"
                },
                "args": {
                    "install_name": spawn_uuid,
                    "matrix": "matrix",
                    "spawner": self._trust_tree.get("spawner_id", "matrix"),
                    "universal_id": universal_id,
                    "agent_name": agent_name,
                    "universe": universe_id,
                    "site_root_path": self.site_root_path
                },
                "tree_node": tree_node,
                "secure_keys": tree_node["secure_keys"]
            }

            python_site_path = site.getsitepackages()[0]
            env = build_encrypted_spawn_env(payload, vault_path)

            env.update({
                "SITE_ROOT": self.site_root_path,
                "AGENT_PATH": self.agent_path,
                "PYTHON_SITE": python_site_path
            })

            pubkey = tree_node["secure_keys"]["pub"]
            fp = hashlib.sha256(pubkey.encode()).hexdigest()[:12]
            logger.log(f"[SPAWN] Using injected pubkey: {fp}")

            process = subprocess.Popen(
                cmd,
                stdout=stdout,
                stderr=stderr,
                stdin=stdin,
                preexec_fn=os.setsid,
                env=env
            )

            pid = process.pid
            try:
                spawn_record = {
                    "uuid": spawn_uuid,
                    "universal_id": universal_id,
                    "agent_name": agent_name,
                    "parent": spawner,
                    "timestamp": timestamp,
                    "pid": pid
                }

                spawn_dir = os.path.join(self.comm_path, universal_id, "spawn")
                os.makedirs(spawn_dir, exist_ok=True)

                filename = f"{timestamp}_{spawn_uuid}.spawn"
                filepath = os.path.join(spawn_dir, filename)

                with open(filepath, "w") as f:
                    json.dump(spawn_record, f, indent=2)

                logger.log(f"[SPAWN-LOG] Spawn recorded at {filepath}")
            except Exception as e:
                logger.log(f"[SPAWN-LOG-ERROR] Failed to log spawn for {universal_id}: {e}")

            install = {
                "universal_id": universal_id,
                "boot_time": timestamp,
                "pid": process.pid,
                "cmd": cmd
            }

            with open(os.path.join(self.pod_path, spawn_uuid, "boot.json"), "w") as f:
                json.dump(install, f, indent=4)


        except Exception as e:
            logger.log(f"[SPAWN-ERROR] Source path not resolved or file missing. Cannot boot agent: {agent_name}")
            logger.log(f"[SPAWN-TRACEBACK] {traceback.format_exc()}")

            raise RuntimeError(f"[SPAWN-FAIL] Missing source for agent {agent_name} at {source_path}")

        return process.pid, cmd