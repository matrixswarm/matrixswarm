
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
import copy

from string import Template
from agent.core.boot_agent import BootAgent

from agent.core.tree_parser import TreeParser
from agent.core.mixin.delegation import DelegationMixin
from agent.core.class_lib.file_system.util.json_safe_write import JsonSafeWrite
from agent.core.class_lib.file_system.util.ensure_trailing_slash import EnsureTrailingSlash
from agent.core.swarm_manager import SwarmManager  # adjust path to match
from agent.reaper.reaper_factory import make_reaper_node
from agent.core.class_lib.hive.kill_chain_lock_manager import KillChainLockManager
from agent.core.utils.swarm_sleep import interruptible_sleep
from agent.core.utils.tree_backup import backup_agent_tree

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
        #    self.command_line_args["universal_id"],  # dynamically resolves to 'matrix'
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
        universal_id = self.command_line_args.get("universal_id", "matrix")
        self.delegate_tree_to_agent(self.command_line_args.get("universal_id", universal_id))
        self.broadcast(f"Delivered agent_tree slice to self ({universal_id})", severity="info")
        #
        threading.Thread(target=self.comm_directory_watcher, daemon=True).start()
        print(message)
        self.broadcast(message)

    def worker_pre(self):
        self.log("[MATRIX] Pre-boot checks complete. Swarm ready.")

    def worker_post(self):
        self.log("[MATRIX] Matrix shutting down. Closing directives.")

    def broadcast(self, message, severity="info"):
        try:

            #this folder is always dropped, even if mailman not installed
            mailman_dir = os.path.join(self.path_resolution["comm_path"], "mailman-1", "payload")
            os.makedirs(mailman_dir, exist_ok=True)

            payload = {
                "uuid": self.command_line_args.get("universal_id", "matrix"),
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

    # watches comm for any added universal_ids, and adds the agent_tree instantly
    def comm_directory_watcher(self):
        print("[COMM-WATCHER] Watching /comm/ for new agents...")
        i = inotify.adapters.Inotify()
        i.add_watch(self.path_resolution["comm_path"])

        for event in i.event_gen(yield_nones=False):
            (_, type_names, path, filename) = event

            if "IN_CREATE" in type_names or "IN_MOVED_TO" in type_names:
                try:
                    # Only act on new directories (universal_ids)
                    full_path = os.path.join(path, filename)
                    if os.path.isdir(full_path):
                        print(f"[COMM-WATCHER] New comm directory detected: {filename}")
                        self.delegate_tree_to_agent(filename)
                except Exception as e:
                    self.log(f"[COMM-WATCHER-ERROR] {e}")


    def delegate_tree_to_agent(self, universal_id):
        try:
            tree_path = os.path.join(self.path_resolution['comm_path'], 'matrix', 'agent_tree_master.json')
            tp = TreeParser.load_tree(tree_path)
            if not tp:
                self.log(f"[DELEGATE] Failed to load master tree for {universal_id}")
                return

            subtree = tp.extract_subtree_by_id(universal_id)
            if not subtree:
                self.log(f"[DELEGATE] No subtree found for {universal_id}, sending empty tree.")
                subtree = {}

            out_path = os.path.join(self.path_resolution["comm_path"], universal_id, "agent_tree.json")
            JsonSafeWrite.safe_write(out_path, subtree)
            self.log(f"[DELEGATE] Tree delivered to {universal_id}")
        except Exception as e:
            self.log(f"[DELEGATE-ERROR] {e}")

    #commands coming off the wire
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

    #executing commands
    def command_listener(self):
        path = Template(self.path_resolution["incoming_path_template"])
        incoming_path = path.substitute(universal_id=self.command_line_args["matrix"])
        incoming_path = EnsureTrailingSlash.ensure_trailing_slash(incoming_path)

        payload_dir = os.path.join(self.path_resolution["comm_path"], "matrix", "payload")
        os.makedirs(payload_dir, exist_ok=True)

        print(f"[CMD-LISTENER] Listening for commands in {incoming_path} and payloads...")

        while self.running:
            try:
                # Handle tree refresh requests
                for filename in glob.glob(incoming_path + '*:_tree_slice_request.cmd'):
                    try:
                        os.remove(filename)
                        universal_id = os.path.basename(filename).split(':')[0].strip()
                        if not universal_id:
                            raise ValueError(f"[TREE-REFRESH][ERROR] No universal_id in filename {filename}")

                        target_incoming_path = os.path.join(self.path_resolution['comm_path'], universal_id, 'agent_tree.json')
                        tree_path = os.path.join(self.path_resolution['comm_path'], self.command_line_args["matrix"], 'agent_tree_master.json')

                        tp = TreeParser.load_tree(tree_path)
                        if not tp:
                            self.log("[TREE-REFRESH][ERROR] Failed to load tree.")
                            continue

                        subtree = tp.extract_subtree_by_id(universal_id) or {}
                        JsonSafeWrite.safe_write(target_incoming_path, subtree)
                        self.log(f"[TREE-REFRESH] Tree slice sent to {universal_id}.")

                    except Exception as e:
                        self.log(f"[TREE-REFRESH][ERROR] {e}")

                # Handle payload commands
                for fname in sorted(os.listdir(payload_dir)):
                    fpath = os.path.join(payload_dir, fname)
                    if not fname.endswith(".json"):
                        continue
                    try:
                        with open(fpath) as f:
                            payload = json.load(f)
                    except Exception as e:
                        self.log(f"[PAYLOAD][ERROR] Failed to parse {fname}: {e}")
                        os.remove(fpath)
                        continue

                    if payload.get("type") == "payload":
                        content = payload.get("payload", {})
                        ctype = content.get("type")
                    else:
                        content = payload
                        ctype = payload.get("type")

                    if ctype == "spawn_agent":
                        self.log(f"[SPAWN] Now injecting agent: {content.get('universal_id')}")
                        self.swarm.handle_injection(content)

                    elif ctype == "inject":
                        self.log(f"[INJECT] Injecting agent from payload.")
                        self.swarm.handle_injection(content)

                    elif ctype == "node_query":
                        requestor = content.get("requestor")
                        target_universal_id = content.get("universal_id")

                        tree_path = os.path.join(self.path_resolution['comm_path'], self.command_line_args["matrix"], 'agent_tree_master.json')
                        tp = TreeParser.load_tree(tree_path)

                        node = tp.get_node(target_universal_id)

                        reply = {
                            "type": "node_response",
                            "content": {
                                "universal_id": target_universal_id,
                                "node": node
                            }
                        }

                        outbox = os.path.join(self.path_resolution['comm_path'], requestor, "incoming")
                        os.makedirs(outbox, exist_ok=True)
                        response_file = os.path.join(outbox, f"node_response_{target_universal_id}.json")

                        with open(response_file, "w") as f:
                            json.dump(reply, f, indent=2)

                        self.log(f"[MATRIX] Sent node response for {target_universal_id} to {requestor}.")
                    elif ctype == "inject_team":
                        self.log(f"[INJECT-TEAM] Injecting agent team.")
                        self.swarm.handle_team_injection(content.get("subtree"), content.get("target_universal_id"))

                    elif ctype == "stop":
                        targets = content.get("targets", [])
                        if isinstance(targets, str):
                            targets = [targets]
                        for t in targets:
                            self.swarm.kill_agent(t, annihilate=False)
                            self.log(f"[STOP] Sent stop signal to {t}")

                    elif ctype == "kill":

                        # Load and snapshot
                        tree_path = os.path.join(self.path_resolution['comm_path'], self.command_line_args["matrix"], 'agent_tree_master.json')

                        tp = TreeParser.load_tree(tree_path)
                        if tp is None:
                            self.log("[KILL][ERROR] Tree load failed, aborting kill.")
                            return

                        original_tree = copy.deepcopy(tp.root)

                        self.log(f"[KILL][DEBUG] Raw content: {json.dumps(content, indent=2)}")

                        kill_list = self.collect_kill_list(tp, content.get("target"))
                        self.log(f"[KILL] Kill List: {kill_list}")

                        kcm = KillChainLockManager(tp)
                        kcm.lock_targets(kill_list)

                        if tp.root != original_tree:
                            backup_dir = os.path.join(os.path.dirname(tree_path), "backups")
                            os.makedirs(backup_dir, exist_ok=True)
                            backup_agent_tree(tree_path, backup_dir=backup_dir,
                                              replaced_node_id=content.get("target"),
                                              new_node_id="reaper-hot-" + str(int(time.time())))
                            tp.save_tree(tree_path)
                            self.log("[KILL] Tree modified — backup created and saved.")
                        else:
                            self.log("[KILL] Tree unchanged — no backup or save needed.")

                        self.log(f"[KILL][DEBUG] Current tree nodes: {list(tp.nodes.keys())}")
                        self.log(f"[KILL][DEBUG] Target exists? {'oracle-1' in tp.nodes}")

                        reaper_node = make_reaper_node(kill_list, {k: k for k in kill_list})
                        self.spawn_agent_direct(reaper_node["universal_id"], reaper_node["name"], reaper_node)

                        self.delegation_refresh()
                        self.log(f"[KILL] Reaper dispatched for {kill_list}")


                    elif ctype == "forward":
                        target = payload.get("target")
                        inner = payload.get("payload")
                        if target and inner:
                            fwd_path = os.path.join(self.path_resolution["comm_path"], target, "payload")
                            os.makedirs(fwd_path, exist_ok=True)
                            fname = f"forwarded_{int(time.time())}.json"
                            with open(os.path.join(fwd_path, fname), "w") as f:
                                json.dump(inner, f, indent=2)
                            self.log(f"[FORWARD] Payload forwarded to {target}")

                    elif ctype == "replace_agent":
                        self.handle_replace_agent(payload.get("content", {}))

                    else:
                        self.log(f"[PAYLOAD][UNKNOWN] Unrecognized payload type: {ctype}")

                    # Always clean up payload file
                    os.remove(fpath)
                    self.log(f"[PAYLOAD] Processed: {fname}")

                # Sanity: Make sure agents have updated trees
                self.perform_tree_master_validation()

                # Breath control
                interruptible_sleep(self, 2)

            except Exception as e:
                self.log(f"[COMMAND-LISTENER][CRASH] {e}")
                interruptible_sleep(self, 3)

    def collect_kill_list(self, tp, universal_id):

        if not tp or not universal_id:
            self.log("[KILL][ERROR] Missing tree or target universal_id.")
            return []

        self.log(f"[KILL][DEBUG] Attempting to collect kill list for: {universal_id}")
        self.log(f"[KILL][DEBUG] Tree contains: {len(tp.nodes)} nodes")
        self.log(f"[KILL][DEBUG] Tree keys: {list(tp.nodes.keys())}")

        if not tp.has_node(universal_id):
            self.log(f"[KILL][DEBUG] Node '{universal_id}' not found in index.")
            return []

        if not tp._find_node(tp.root, universal_id):
            self.log(f"[KILL][DEBUG] Node '{universal_id}' exists but is disconnected from root. Skipping.")
            return []

        subtree = tp.get_subtree_nodes(universal_id)

        if not subtree:
            self.log(f"[KILL][DEBUG] Subtree for '{universal_id}' is empty.")
        else:
            self.log(f"[KILL][DEBUG] Subtree for '{universal_id}' → {subtree}")

        return subtree


    #send a copy of agent_tree to each node
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

                for universal_id in os.listdir(self.path_resolution["comm_path"]):
                    target_dir = os.path.join(self.path_resolution["comm_path"], universal_id)
                    if not os.path.isdir(target_dir):
                        continue

                    tree_path = os.path.join(target_dir, "agent_tree.json")
                    needs_update = False

                    # Get what SHOULD be there
                    expected_subtree = tp.extract_subtree_by_id(universal_id)
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
                            self.log(f"[VERIFY-TREE] {universal_id} tree parse fail: {e}")
                            needs_update = True

                    if needs_update:
                        self.delegate_tree_to_agent(universal_id)
                        self.broadcast(f"Refreshed agent_tree for {universal_id}", severity="info")

        except Exception as e:
            self.log(f"[VERIFY-TREE] Error: {e}")

    def delegation_refresh(self):
        """
        TREE BULWARK DEFENDER III — Deletion Mode:
        Purge tombstoned agents entirely from agent_tree_master.json.
        """
        try:
            self.log("[BULWARK] Starting Full Delegation Refresh (Deletion Mode)...")

            tree_path = os.path.join(self.path_resolution['comm_path'], 'matrix', 'agent_tree_master.json')
            tp = TreeParser.load_tree(tree_path)
            if not tp:
                self.log("[BULWARK] Could not load tree. Abort delegation refresh.")
                return

            pod_root = self.path_resolution['pod_path']
            comm_root = self.path_resolution['comm_path']

            dead_universal_ids = set()

            for universal_id in list(tp.get_all_nodes_flat()):
                if universal_id == "matrix":
                    continue  # Never remove matrix herself

                pod_uuid = None
                for pod_dir in os.listdir(pod_root):
                    try:
                        boot_path = os.path.join(pod_root, pod_dir, "boot.json")
                        if not os.path.exists(boot_path):
                            continue
                        with open(boot_path, "r") as f:
                            boot_data = json.load(f)
                        if boot_data.get("universal_id") == universal_id:
                            pod_uuid = pod_dir
                            break
                    except Exception:
                        continue

                comm_tombstone = os.path.join(comm_root, universal_id, "incoming", "tombstone")
                pod_tombstone = os.path.join(pod_root, pod_uuid, "tombstone") if pod_uuid else None

                tombstone_found = False
                if os.path.exists(comm_tombstone):
                    tombstone_found = True
                elif pod_tombstone and os.path.exists(pod_tombstone):
                    tombstone_found = True

                if tombstone_found:
                    dead_universal_ids.add(universal_id)

            if not dead_universal_ids:
                self.log("[BULWARK] No tombstoned agents found. Hive remains at full strength.")
                return

            for dead_id in dead_universal_ids:
                try:
                    tp.remove_node(dead_id)
                    self.log(f"[BULWARK] Purged fallen agent: {dead_id}")
                except Exception as e:
                    self.log(f"[BULWARK][ERROR] Failed to purge {dead_id}: {e}")

            tp.save_tree(tree_path)
            self.log("[BULWARK] Delegation Refresh Completed. Battlefield memory locked.")

        except Exception as e:
            self.log(f"[BULWARK][CRASH] {e}")

    def propagate_all_delegates(self):

        from agent.core.tree_propagation import propagate_tree_slice

        tree_path = os.path.join(self.path_resolution['comm_path'], 'matrix', 'agent_tree.json')
        tp = TreeParser.load_tree(tree_path)
        if not tp:
            self.log("[PROPAGATE] Failed to load tree.")
            return

        all_nodes = tp.get_all_nodes_flat()
        for universal_id in all_nodes:
            propagate_tree_slice(tp, universal_id, self.path_resolution["comm_path"])

    def handle_replace_agent(self, content):
        old_id = content.get("target_universal_id")
        new_node = content.get("new_agent")
        hotswap = content.get("hotswap", False)

        if not old_id or not new_node:
            self.log("[REPLACE] Missing required fields.")
            return

        tree_path = self.tree_path
        tp = TreeParser.load_tree(tree_path)
        if not tp or not tp.has_node(old_id):
            self.log(f"[REPLACE] Agent '{old_id}' not found in tree.")
            return

        parent = tp.find_parent_of(old_id)
        if not parent:
            self.log(f"[REPLACE] Could not find parent of '{old_id}'.")
            return

        # Update existing node in-place instead of removing
        node = tp.get_node(old_id)
        node.update(new_node)  # Overwrites name, config, etc.
        tp.save_tree(tree_path)

        # Create reaper node with selective tombstone
        from agent.reaper.reaper_factory import make_reaper_node
        kill_list = [old_id]
        universal_ids = {old_id: old_id}
        reaper = make_reaper_node(kill_list, universal_ids)
        if hotswap:
            reaper["config"]["tombstone_comm"] = False  # only pod gets tomb

        self.spawn_agent_direct(reaper["universal_id"], reaper["name"], reaper)

        self.log(f"[REPLACE] Agent {old_id} replaced in tree and reaper dispatched.")

if __name__ == "__main__":
    # label = None
    # if "--label" in sys.argv:
    #   label = sys.argv[sys.argv.index("--label") + 1]

    # current directory of the agent script or it wont be able to find itself
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))

    matrix = MatrixAgent(path_resolution, command_line_args)

    matrix.boot()
