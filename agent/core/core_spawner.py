# At the top of your script
import sys
import os
import textwrap
from unicodedata import unidata_version

# Add the directory containing this script to the PYTHONPATH
current_directory = os.path.dirname(os.path.abspath(__file__))  # Directory of the current script
if current_directory not in sys.path:
    sys.path.insert(0, current_directory)

import json
import time
import uuid
import shutil
import subprocess
import traceback
from datetime import datetime
from class_lib.file_system.file_system_builder import FileSystemBuilder
from path_manager import PathManager
from agent.core.class_lib.logging.logger import Logger

class CoreSpawner:
    def __init__(self, site_root="/sites/orbit/python", comm_root="matrixline", pod_root="pod"):

        pm=PathManager()

        paths = {
            "pod": "pod",
            "agent": "agent",
            "comm": "comm",
        }

        pm.add_paths(paths)

        self.root_path = pm.get_path("root")

        self.comm_path = pm.get_path("comm")

        self.pod_path = pm.get_path("pod")

        self.agent_path = pm.get_path("agent")

        os.makedirs(self.comm_path, exist_ok=True)

        os.makedirs(self.pod_path, exist_ok=True)


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

    def ensure_comm_channel(self, permanent_id, file_spec, agent_directive=None):

        base = os.path.join(self.comm_path, permanent_id)

        os.makedirs(base, exist_ok=True)

        print('comm_channel creation: start')

        # Always process the default file_spec
        fsb = FileSystemBuilder()
        fsb.process_selection(base, file_spec)

        # If agent_directive contains additional filesystem specs
        if agent_directive:
            fs_node = agent_directive if isinstance(agent_directive, dict) and "folders" in agent_directive else {}
            print(f"[DEBUG] Processing filesystem spec: {fs_node}")

            folders = fs_node.get("folders", [])
            if folders:
                print(f"[FS-BUILDER] Merging folders from directive for {permanent_id}")
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

    def create_runtime(self, permanent_id):
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

    def spawn_agent(self, universe_id, spawn_uuid, agent_name, permanent_id, spawner, tree_node=None):

        try:

            spawn_path = os.path.join(self.pod_path, spawn_uuid)
            os.makedirs(spawn_path, exist_ok=True)

            #get source agent
            #paste it to run tme
            full_path = os.path.join(self.agent_path, agent_name, agent_name+'.py')

            run_path = os.path.join(spawn_path, "run")

            # Open the file in read mode
            with open(full_path, "r") as f:
                file_content = f.read()  # Read the entire file content

            path_resolver = textwrap.dedent("""
            import sys
            if path_resolution['agent_path'] not in sys.path:
                sys.path.append(path_resolution['agent_path'])
            if path_resolution['root_path'] not in sys.path:
                sys.path.append(path_resolution['root_path'])
            """)

            #when the process is spawned it has no way to find the root and the lib path
            #so prepend it with these facts
            root_path = '"root_path": "' + self.root_path + '",' + "\n"
            pod_path = '"pod_path": "' + self.pod_path + '",' + "\n"
            comm_path = '"comm_path": "' + self.comm_path + '",'+ "\n"
            agent_path = '"agent_path": "' + self.agent_path + '",' + "\n"
            incoming_path_template = '"incoming_path_template": "' + os.path.join(self.comm_path, '$permanent_id', "incoming") + '",' + "\n"
            comm_path_resolved = '"comm_path_resolved": "' +  os.path.join(self.comm_path, permanent_id) + '",' + "\n"

            matrix_name = '"matrix": "matrix",' + "\n"
            universe_name = '"universe_id": "' + universe_id + '",' + "\n"
            spawner_name = '"spawner": "' + spawner + '",' + "\n"
            permanent_id_name = '"permanent_id": "' + permanent_id + '",' + "\n"
            agent_name_name = '"agent_name": "' + agent_name + '",' + "\n"
            install_name = '"install_name": "' + spawn_uuid + '",' + "\n"

            #written to the top of the script, runtime src
            path_resolution = 'path_resolution={\n'+ root_path + pod_path + comm_path + agent_path + incoming_path_template + comm_path_resolved + '}\n' + path_resolver
            command_line_args = 'command_line_args={\n' + install_name + matrix_name + universe_name + spawner_name + permanent_id_name + agent_name_name + '}\n'

            tree_node_blob = ""
            if tree_node:
                try:
                    tree_node_blob = f"tree_node = {repr(tree_node)}\n"
                except Exception as e:
                    print(f"[SPAWN-ERROR] Could not encode tree_node for {permanent_id}: {e}")


            with open(run_path, "w") as f:
                f.write(path_resolution + command_line_args + tree_node_blob + file_content)


            #payload = json.dumps(live_data).encode("utf-8")
            #encrypted = core.encrypt(payload)
            #with open(os.path.join(spawn_path, "live.json.enc"), "wb") as f:
             #   f.write(encrypted)

            logger = Logger(comm_path_resolved)

            # WRITE SPAWN LOG
            # Log the spawn to /comm/{perm_id}/spawn/
            try:
                spawn_record = {
                    "uuid": spawn_uuid,
                    "permanent_id": permanent_id,
                    "agent_name": agent_name,
                    "parent": spawner,
                    "timestamp": time.time()
                }

                spawn_dir = os.path.join(self.comm_path, permanent_id, "spawn")
                os.makedirs(spawn_dir, exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{timestamp}_{spawn_uuid}.spawn"
                filepath = os.path.join(spawn_dir, filename)

                with open(filepath, "w") as f:
                    json.dump(spawn_record, f, indent=2)

                logger.log(f"[SPAWN-LOG] Spawn recorded at {filepath}")
            except Exception as e:
                logger.log(f"[SPAWN-LOG-ERROR] Failed to log spawn for {permanent_id}: {e}")

            #GO TIME
            logger.log(f"[SPAWN-MGR] About to spawn: {permanent_id}")

            cmd = [
                "python3",
                run_path,
                "--job", f"{universe_id}:{spawner}:{permanent_id}:{agent_name}",
                "--ts", datetime.now().strftime("%Y%m%d%H%M%S%f")
            ]

            process = subprocess.Popen(
                cmd,
                #stderr=subprocess.DEVNULL,
                #stdout=subprocess.DEVNULL,
                #stdin=subprocess.DEVNULL,
                #preexec_fn=os.setsid

            )

            install = {
                "permanent_id": permanent_id,
                "boot_time": time.time(),
                "pid": process.pid,
                "cmd": cmd
            }
            with open(os.path.join(self.pod_path, spawn_uuid, "boot.json"), "w") as f:
                json.dump(install, f, indent=4)


        except Exception as e:
            print(f"[SPAWN-ERROR] Failed to spawn {agent_name}: {e}\n{traceback.format_exc()}")
            return None

        return process.pid, cmd