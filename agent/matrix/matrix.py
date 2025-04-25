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
import glob
import inotify
import inotify.adapters
import threading
import hashlib
import json
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
        # Manually check if our own comm directory exists (it does), and deliver the tree slice directly
        perm_id = self.command_line_args.get("permanent_id", "matrix")
        self.delegate_tree_to_agent(self.command_line_args.get("permanent_id", perm_id))
        self.broadcast(f"Delivered agent_tree slice to self ({perm_id})", severity="info")


        threading.Thread(target=self.comm_directory_watcher, daemon=True).start()
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

    def file_hash(path):
        with open(path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()

    def json_hash(obj):
        return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()

    # watches comm for any added permanent_ids, and adds the agent_tree instantly
    def comm_directory_watcher(self):
        print("[COMM-WATCHER] Watching /comm/ for new agents...")
        i = inotify.adapters.Inotify()
        i.add_watch(self.path_resolution["comm_path"])

        for event in i.event_gen(yield_nones=False):
            (_, type_names, path, filename) = event

            if "IN_CREATE" in type_names or "IN_MOVED_TO" in type_names:
                try:
                    # Only act on new directories (perm_ids)
                    full_path = os.path.join(path, filename)
                    if os.path.isdir(full_path):
                        print(f"[COMM-WATCHER] New comm directory detected: {filename}")
                        self.delegate_tree_to_agent(filename)
                except Exception as e:
                    self.log(f"[COMM-WATCHER-ERROR] {e}")


    def delegate_tree_to_agent(self, perm_id):
        try:
            tree_path = os.path.join(self.path_resolution['comm_path'], 'matrix', 'agent_tree_master.json')
            tp = TreeParser.load_tree(tree_path)
            if not tp:
                self.log(f"[DELEGATE] Failed to load master tree for {perm_id}")
                return

            subtree = tp.extract_subtree_by_id(perm_id)
            if not subtree:
                self.log(f"[DELEGATE] No subtree found for {perm_id}, sending empty tree.")
                subtree = {}

            out_path = os.path.join(self.path_resolution["comm_path"], perm_id, "agent_tree.json")
            JsonSafeWrite.safe_write(out_path, subtree)
            self.log(f"[DELEGATE] Tree delivered to {perm_id}")
        except Exception as e:
            self.log(f"[DELEGATE-ERROR] {e}")

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

                    elif ctype == "kill":
                        target_id = content.get("target")
                        subtree = self.tree_parser.get_subtree_nodes(target_id)
                        kill_list = subtree if subtree else [target_id]

                        self.spawn_agent(
                            f"reaper-mission-{uuid4()}",
                            type="DisposableReaperAgent",
                            args={
                                "targets": kill_list,
                                "kill_id": f"kill-{target_id}-{int(time.time())}"
                            }
                        )
                        self.log(f"[MATRIX][KILL] Dispatched kill op for {kill_list}")


                    os.remove(fpath)
                    self.log(f"[PAYLOAD] Processed: {fname}")

                time.sleep(2)
            except Exception as e:

                self.log(f"[PAYLOAD] Error: {e} : {payload}")
                time.sleep(3)


            #SANITY CHECK: make sure all nodes are up to date with agent_tree.json
            self.perform_tree_master_validation()

            time.sleep(4)

    def perform_tree_master_validation(self):
        def canonical_json(obj):
            """
            Canonical JSON serializer: compact, ordered, no random whitespace or key ordering differences.
            """
            return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True)

        try:
            if not hasattr(self, "_last_tree_verify"):
                self._last_tree_verify = 0

            if time.time() - self._last_tree_verify > 300:  # 5-minute window
                self._last_tree_verify = time.time()

                static_tree_path = os.path.join(self.path_resolution['comm_path'], 'matrix', 'agent_tree_master.json')
                tp = TreeParser.load_tree(static_tree_path)
                if not tp:
                    self.log("[VERIFY-TREE] Could not load master tree.")
                    return

                for perm_id in os.listdir(self.path_resolution["comm_path"]):
                    target_dir = os.path.join(self.path_resolution["comm_path"], perm_id)
                    if not os.path.isdir(target_dir):
                        continue

                    tree_path = os.path.join(target_dir, "agent_tree.json")
                    needs_update = False

                    # Get what SHOULD be there
                    expected_subtree = tp.extract_subtree_by_id(perm_id)
                    if not expected_subtree:
                        expected_subtree = {}

                    expected_hash = hashlib.sha256(canonical_json(expected_subtree).encode()).hexdigest()

                    if not os.path.exists(tree_path):
                        needs_update = True
                    else:
                        try:
                            with open(tree_path, "r") as f:
                                current_tree = json.load(f)
                                current_hash = hashlib.sha256(canonical_json(current_tree).encode()).hexdigest()
                                if current_hash != expected_hash:
                                    needs_update = True
                        except Exception as e:
                            self.log(f"[VERIFY-TREE] {perm_id} tree parse fail: {e}")
                            needs_update = True

                    if needs_update:
                        self.delegate_tree_to_agent(perm_id)
                        self.broadcast(f"Refreshed agent_tree for {perm_id}", severity="info")

        except Exception as e:
            self.log(f"[VERIFY-TREE] Error: {e}")



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
