#Authored by Daniel F MacDonald and ChatGPT aka The Generals
# ╔════════════════════════════════════════════════════════╗
# ║                   🧠 MATRIX AGENT 🧠                   ║
# ║   Central Cortex · Tree Dispatcher · Prime Director    ║
# ║     Forged in the core of Hive Zero | v3.0 Directive   ║
# ║  Accepts: inject / replace / resume / kill / propagate ║
# ╚════════════════════════════════════════════════════════╝
# ╔═════════════════════════════════════════════════════════════╗
# ║   THE SWARM IS ALIVE — AGENTS COMING OUT OF EVERY ORIFICE  ║
# ║       Please take as many as your system can support        ║
# ╚═════════════════════════════════════════════════════════════╝

# Disclaimer: If your system catches fire, enters recursive meltdown,
# or you OD on die cookies — just remember: we met at a Star Trek convention.
# You were dressed as Data. I was the Captain. That’s all we know about each other.
#He said something about agents… then started telling people to fork off.
#I don’t know, something was up with that guy.
import os
import time
import json
import hashlib
import glob
from string import Template

from agent.core.boot_agent import BootAgent

from agent.core.tree_parser import TreeParser
from agent.core.mixin.delegation import DelegationMixin
from agent.core.class_lib.file_system.util.json_safe_write import JsonSafeWrite
from agent.core.class_lib.file_system.util.ensure_trailing_slash import EnsureTrailingSlash
from agent.core.tree_propagation import propagate_tree_slice
from agent.core.swarm_manager import SwarmManager  # adjust path to match


class MatrixAgent(DelegationMixin, BootAgent):

    def __init__(self, path_resolution, command_line_args):

        super().__init__(path_resolution, command_line_args)

        self.path_resolution=path_resolution

        self.command_line_args=command_line_args

        self.orbits = {}

        self.swarm = SwarmManager(path_resolution)


        #from agent.core.tree_disseminator import TreeDisseminator

        #tree_path = os.path.join(
        #    self.path_resolution["comm_path"],
        #    self.command_line_args["permanent_id"],  # dynamically resolves to 'matrix'
        #    "agent_tree.json"
        #)

        #self.disseminator = TreeDisseminator(tree_path, self.path_resolution["comm_path"])

        #start_https_server(self, port=65431)

    def pre_boot(self):
        message = "Knock... Knock... Knock... The Matrix has you..."
        print(message)
        self.broadcast(message)

    def post_boot(self):
        message = "I'm watching..."
        print(message)
        self.broadcast(message)

    def broadcast(self, message, severity="info"):
        try:
            mailman_dir = os.path.join(self.path_resolution["comm_path"], "mailman-1", "payload")
            os.makedirs(mailman_dir, exist_ok=True)

            payload = {
                "uuid": self.command_line_args.get("permanent_id", "matrix"),
                "timestamp": time.time(),
                "severity": severity,
                "msg": message
            }

            fname = f"matrix_broadcast_{int(time.time())}.json"
            with open(os.path.join(mailman_dir, fname), "w") as f:
                json.dump(payload, f, indent=2)

        except Exception as e:
            self.log(f"[MATRIX][BROADCAST-ERROR] {e}")

    def handle_https_command(self, data):
        try:
            comm_path = "/comm/matrix/payload"
            os.makedirs(comm_path, exist_ok=True)

            # Create unique filename with timestamp + hash
            timestamp = int(time.time() * 1000)
            payload_str = json.dumps(data, sort_keys=True)
            payload_hash = hashlib.sha256(payload_str.encode()).hexdigest()[:12]
            filename = f"{timestamp}_{payload_hash}.json"
            full_path = os.path.join(comm_path, filename)

            # Write command to payload folder
            with open(full_path, "w") as f:
                f.write(payload_str)

            print(f"[MATRIX:HTTPS] Command routed to payload: {filename}")
        except Exception as e:
            print(f"[MATRIX:HTTPS-ERROR] Failed to dispatch command: {e}")




    def command_listener(self):

        path = Template(self.path_resolution["incoming_path_template"])
        incoming_path = path.substitute(permanent_id=self.command_line_args["matrix"])
        incoming_path = EnsureTrailingSlash.ensure_trailing_slash(incoming_path)

        payload_dir = os.path.join(self.path_resolution["comm_path"], "matrix", "payload")
        os.makedirs(payload_dir, exist_ok=True)

        print(f"[CMD-LISTENER] Listening for commands in {incoming_path}...")

        while self.running:
            try:
                # TREE REFRESH COMMAND
                for filename in glob.glob(incoming_path + '*:_tree_slice_request.cmd'):

                    #No need for the command junk it
                    os.remove(filename)

                    # Extract the file name without the path or extension
                    filename = os.path.basename(filename)  # Get the file name with extension, e.g., "example_tree_slice_request.cmd"
                    filename = os.path.splitext(filename)[0]
                    perm_id = filename.split(':')[0].strip() # Strip the command, e.g., "*:_tree_slice_request.cmd"

                    # Raise an exception if perm_id is empty
                    if not perm_id:
                        raise ValueError(f"[MATRIX][ERROR] permanent_id is empty for the file: {filename}")

                    target_incoming_path = os.path.join(self.path_resolution['comm_path'], perm_id, 'agent_tree.json')

                    tree_path = os.path.join(self.path_resolution['comm_path'], self.command_line_args["matrix"], 'agent_tree_master.json')

                    tp = TreeParser.load_tree(tree_path)
                    if not tp:
                        self.log("[PROPAGATE] Failed to load tree.")
                        return

                    subtree = tp.extract_subtree_by_id(perm_id)
                    if not subtree:
                        print(f"[PROPAGATION] No subtree found for {perm_id}")
                        subtree = {}

                    try:
                        safe_preview = json.dumps(subtree, default=str, indent=2)[:300]
                    except TypeError as e:
                        safe_preview = f"[NON-SERIALIZABLE SLICE] {e}"

                    self.log(f"[TREE-DISPATCH] Sending to {perm_id}: {safe_preview}")

                    #copy from agent_tree_master.json
                    JsonSafeWrite.safe_write(target_incoming_path, subtree)

            except Exception as e:
                self.log(f"[CMD-ERROR][TREE-REFRESH] {e}")

            # PAYLOADS OFF THE WIRE
            try:
                for fname in sorted(os.listdir(payload_dir)):
                    if not fname.endswith(".json"):
                        continue

                    fpath = os.path.join(payload_dir, fname)
                    with open(fpath) as f:
                        payload = json.load(f)

                    ctype = payload.get("type")
                    content = payload.get("content", {})
                    #annihilate = content.get("annihilate", True)

                    if ctype == "spawn_agent":
                        self.log(f"[SPAWN] Injecting NOW agent from payload: {content.get('perm_id')}")
                        self.swarm.handle_injection(content)
                        self.log(f"[SPAWN] Injected agent from payload: {content.get('perm_id')}")
                        os.remove(fpath)
                        continue

                    elif ctype == "inject":
                        self.swarm.handle_injection(content)
                    elif ctype == "inject_team":
                        self.swarm.handle_team_injection(
                            content.get("subtree"),
                            content.get("target_perm_id")
                        )

                    elif ctype == "stop":
                        targets = content.get("targets", [])
                        if isinstance(targets, str):
                            targets = [targets]

                        for t in targets:
                            self.swarm.kill_agent(t, annihilate=False)
                            self.log(f"[MATRIX] Stop command dispatched for {t}")

                    elif ctype == "kill":

                        target = content.get("target")

                        mode = content.get("mode", "single")

                        annihilate = content.get("annihilate", True)

                        if mode == "lights_out":

                            self.swarm.kill_all_agents(annihilate=annihilate)

                        elif mode == "subtree":

                            self.swarm.kill_subtree(target, annihilate=annihilate)

                        elif isinstance(target, str):

                            self.swarm.kill_agent(target, annihilate=annihilate)

                        elif isinstance(content.get("targets"), list):

                            for t in content["targets"]:
                                self.swarm.kill_agent(t, annihilate=annihilate)
                    elif ctype == "delete_subtree":
                        self.swarm.kill_subtree(content.get("perm_id"))


                    os.remove(fpath)
                    self.log(f"[PAYLOAD] Processed: {fname}")

                time.sleep(2)
            except Exception as e:

                self.log(f"[PAYLOAD] Error: {e} : {payload}")
                time.sleep(3)

            time.sleep(4)


    def propagate_all_delegates(self):
        from agent.core.tree_parser import TreeParser
        from agent.core.tree_propagation import propagate_tree_slice

        tree_path = os.path.join(self.path_resolution['comm_path'], 'matrix', 'agent_tree.json')
        tp = TreeParser.load_tree(tree_path)
        if not tp:
            self.log("[PROPAGATE] Failed to load tree.")
            return

        all_nodes = tp.get_all_nodes_flat()
        for perm_id in all_nodes:
            propagate_tree_slice(tp, perm_id, self.path_resolution["comm_path"])

    def handle_replace_agent(self, content):
        old_id = content.get("target_perm_id")
        new_node = content.get("new_agent")
        new_id = new_node.get("perm_id")

        if not old_id or not new_node:
            self.log("[REPLACE] Missing required fields.")
            return

        from agent.core.tree_parser import TreeParser

        tree_path = self.tree_path  # or path_resolution["tree_file"]
        tp = TreeParser.load_tree(tree_path)
        if not tp or not tp.has_node(old_id):
            self.log(f"[REPLACE] Agent '{old_id}' not found in tree.")
            return

        # Find parent
        parent = tp.find_parent_of(old_id)
        if not parent:
            self.log(f"[REPLACE] Could not find parent of '{old_id}'.")
            return

        # Send die to old agent
        die_file = os.path.join(self.path_resolution["comm_path"], old_id, "incoming", "die")
        JsonSafeWrite.safe_write(die_file, "terminate")
        self.log(f"[REPLACE] Issued die to {old_id}")

        # Mark tombstone so parent doesn't respawn
        tomb = os.path.join(self.path_resolution["comm_path"], old_id, "incoming", "tombstone")
        JsonSafeWrite.safe_write(tomb, "true")

        # Remove old node from tree
        tp.remove_node(old_id)

        # Inject new node under same parent
        tp.insert_node(new_node, parent_permanent_id=parent)
        tp.save_tree(tree_path)

        # Spawn the new agent
        self.spawn_agent(new_id)
        self.log(f"[REPLACE] Spawned replacement: {new_id}")

if __name__ == "__main__":
    # label = None
    # if "--label" in sys.argv:
    #   label = sys.argv[sys.argv.index("--label") + 1]

    # current directory of the agent script or it wont be able to find itself
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))

    matrix = MatrixAgent(path_resolution, command_line_args)

    matrix.boot()
