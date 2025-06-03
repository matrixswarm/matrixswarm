import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

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
import agent

import os
import time
from pathlib import Path
import inotify
import inotify.adapters
import threading
import hashlib
import json
import copy
import base64
from core.boot_agent import BootAgent
from agent.reaper.reaper_factory import make_reaper_node
from core.mixin.ghost_vault import generate_agent_keypair
from core.tree_parser import TreeParser
from core.class_lib.packet_delivery.utility.encryption.config import ENCRYPTION_CONFIG
from core.mixin.ghost_vault import sign_pubkey_registry, verify_pubkey_registry
from core.trust_templates.matrix_dummy_priv import DUMMY_MATRIX_PRIV

class Agent(BootAgent):
    def __init__(self):
        super().__init__()

        self.orbits = {}

        #self.swarm = SwarmManager(self.path_resolution)

        self.tree_path = os.path.join(
            self.path_resolution["comm_path_resolved"],
            "directive",
            "agent_tree_master.json"
        )

        self.tree_path_dict={
                             "path": self.path_resolution["comm_path"],
                             "address": self.command_line_args.get("universal_id"),
                             "drop": "directive",
                             "name": "agent_tree_master.json"
                             }

        # Inject payload_path if it's not already present
        if "payload_path" not in self.path_resolution:
            self.path_resolution["payload_path"] = os.path.join(
                self.path_resolution["comm_path_resolved"],
                "payload"
            )

        #from core.tree_disseminator import TreeDisseminator

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

    def post_boot(self):
        message = "I'm watching..."
        # Manually check if our own comm directory exists (it does), and deliver the tree slice directly
        universal_id = self.command_line_args.get("universal_id", "matrix")
        self.delegate_tree_to_agent(universal_id, self.tree_path_dict)
        threading.Thread(target=self.comm_directory_watcher, daemon=True).start()
        print(message)

    def worker_pre(self):
        self.log("[MATRIX] Pre-boot checks complete. Swarm ready.")

    def worker_post(self):
        self.log("[MATRIX] Matrix shutting down. Closing directives.")

    def packet_listener_post(self):
        #sanity check
        self.perform_tree_master_validation()


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
                        self.delegate_tree_to_agent(filename, self.tree_path_dict)
                except Exception as e:
                    self.log(f"[COMM-WATCHER-ERROR] {e}")

    def cmd_register_identity(self, content, packet):
        """
        Direct command for identity registration via bootsig.
        Used when sent through .cmd files instead of routed packets.
        """

        embedded = content.get("command", {})
        inner = embedded.get("content", {})

        pubkey = inner.get("pubkey")
        bootsig = inner.get("bootsig")
        uid = inner.get("universal_id", "unknown")


        if not uid or not pubkey or not bootsig:
            self.log("[CMD-IDENTITY][REJECTED] Missing pubkey or bootsig.")
            return

        from core.utils.verify_identity import verify_bootsig
        if not verify_bootsig(pubkey, bootsig):
            self.log(f"[CMD-IDENTITY][FAIL] Invalid bootsig from {uid}")
            return

        path = os.path.join(self.path_resolution["comm_path"], "matrix", "pubkeys.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                pubkeys = json.load(f)
        else:
            pubkeys = {}

        pubkeys[uid] = {
            "pubkey": pubkey,
            "bootsig": bootsig,
            "fingerprint": hashlib.sha256(pubkey.encode()).hexdigest()[:12],
            "timestamp": int(time.time())
        }

        with open(path, "w") as f:
            json.dump(pubkeys, f, indent=2)
            sign_pubkey_registry(self, path)

        self.log(f"[CMD-IDENTITY][REGISTERED] {uid} added to pubkey registry.")

    def cmd_delete_agent(self, content, packet):

        try:
            target = content.get("target_universal_id")
            if not target:
                self.log("[DELETE_AGENT][ERROR] Missing target_universal_id in content.")
                return

            tp = self.load_directive(self.tree_path_dict)
            if tp is None:
                self.log("[DELETE_AGENT][ERROR] Tree load failed, aborting kill.")
                return

            original_tree = copy.deepcopy(tp.root)
            kill_list = self.collect_kill_list(tp, target)

            if tp.root != original_tree:

                data = {"agent_tree": tp.root}
                # use the generalized save_directive method
                self.save_directive(self.tree_path_dict, data)
                self.log("[DELETE_AGENT] Tree modified — backup created and saved.")

            reaper_node = make_reaper_node(kill_list, {k: k for k in kill_list})

            keychain = generate_agent_keypair()
            keychain["swarm_key"] = self.swarm_key
            keychain["matrix_pub"] = self.matrix_pub
            keychain["matrix_priv"] = DUMMY_MATRIX_PRIV
            keychain["encryption_enabled"] = int(self.encryption_enabled)

            self.spawn_agent_direct(reaper_node["universal_id"], reaper_node["name"], reaper_node, keychain=keychain)

            self.delegation_refresh()
            self.log(f"[DELETE_AGENT] Reaper dispatched for {kill_list}")

        except Exception as e:
            self.log(f"[DELETE_AGENT][ERROR] {e}")

    def cmd_agent_status_report(self, content, packet):

        uid = content.get("target_universal_id")
        reply_to = content.get("reply_to", "matrix")
        if not uid:
            self.log("[STATUS_REPORT][ERROR] No target_universal_id.")
            return

        comm_root = self.path_resolution["comm_path"]
        pod_root = self.path_resolution["pod_path"]
        report = {
            "universal_id": uid,
            "status": "unknown",
            "uptime_seconds": None,
            "boot_time": None,
            "pid": None,
            "cli": None,
            "last_heartbeat": None,
            "spawn_records": [],
            "runtime_uuid": None,
            "delegates": []
        }

        # 💓 Heartbeat check
        try:
            ping_path = os.path.join(comm_root, uid, "hello.moto", "poke.heartbeat")
            if os.path.exists(ping_path):
                delta = time.time() - os.path.getmtime(ping_path)
                report["last_heartbeat"] = round(delta, 2)
                report["status"] = "alive" if delta < 20 else "stale"
        except Exception as e:
            self.log(f"[STATUS][HEARTBEAT-ERR] {e}")

        # 🐣 Spawn record lookup
        try:
            spawn_dir = os.path.join(comm_root, uid, "spawn")
            spawns = sorted(Path(spawn_dir).glob("*.spawn"), reverse=True)
            if spawns:
                with open(spawns[0]) as f:
                    info = json.load(f)
                report["runtime_uuid"] = info.get("uuid")
                report["boot_time"] = info.get("timestamp")
                report["cli"] = " ".join(info.get("cmd", []))
                report["pid"] = info.get("pid")

                # ⏱ uptime from PID
                now = time.time()
                from psutil import process_iter
                for proc in process_iter(['pid', 'create_time']):
                    if proc.info['pid'] == report["pid"]:
                        report["uptime_seconds"] = round(now - proc.info["create_time"])
                        break
        except Exception as e:
            self.log(f"[STATUS][SPAWN-ERR] {e}")

        try:
            from core.live_tree import LiveTree
            tree = LiveTree()
            tree.load(self.tree_path)
            report["delegates"] = tree.get_delegates(uid)
        except Exception as e:
            self.log(f"[STATUS][TREE-ERR] {e}")

        try:
            inbox = os.path.join(comm_root, reply_to, "incoming")
            os.makedirs(inbox, exist_ok=True)
            fname = f"status_{uid}_{int(time.time())}.msg"



            #REFACTOR INTO PACKET
            #with open(os.path.join(inbox, fname), "w") as f:
            #    json.dump(report, f, indent=2)




            self.log(f"[STATUS] Sent report on {uid} to {reply_to}")
        except Exception as e:
            self.log(f"[STATUS][REPLY-ERROR] {e}")

    def cmd_forward_command(self, content, packet):
        try:
            target = content.get("target_universal_id")
            folder = content.get("folder", "incoming")
            inner = content.get("command")

            if not (target and inner and inner.get("handler")):
                self.log("[FORWARD][ERROR] Missing required fields.")
                return

            # Deep copy to preserve structure
            forwarded_packet = inner.copy()

            # 💥 Validate again if needed
            if "handler" not in forwarded_packet:
                self.log("[FORWARD][ERROR] Inner packet missing handler.")
                return

            # 🔍 Check if it's a config intent
            is_config_packet = forwarded_packet.get("handler") == "__config__"

            # 📦 Choose packet type
            packet_type = "standard.general.json.packet" if is_config_packet else "standard.command.packet"
            pk = self.get_delivery_packet(packet_type, new=True)
            pk.set_data(forwarded_packet)

            # 🚚 Deliver to the right place
            da = self.get_delivery_agent("file.json_file", new=True)
            da.set_location({"path": self.path_resolution["comm_path"]}) \
                .set_address([target]) \
                .set_drop_zone({"drop": folder}) \
                .set_packet(pk) \
                .deliver()

            if da.get_error_success() == 0:
                self.log(
                    f"[FORWARD] ✅ Forwarded to {target}/{drop_zone}: {forwarded_packet['handler']}: {da.get_sent_packet()}")
            else:
                self.log(f"[FORWARD][FAIL] {da.get_error_success_msg()}")

        except Exception as e:
            self.log(f"[FORWARD][CRASH] {e}")

    #CLEAR
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

    #removes dead agents from matrix/directive/agent_tree_master.json
    def delegation_refresh(self):
        """
        TREE BULWARK DEFENDER III — Deletion Mode:
        Purge tombstoned agents entirely from agent_tree_master.json.
        """
        try:
            self.log("[BULWARK] Starting Full Delegation Refresh (Deletion Mode)...")

            tp = self.load_directive(self.tree_path_dict)
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

            data = {"agent_tree": tp.root}
            self.save_directive(self.tree_path_dict , data)

            self.log("[BULWARK] Delegation Refresh Completed. Battlefield memory locked.")

        except Exception as e:
            self.log(f"[BULWARK][CRASH] {e}")

    def cmd_hotswap_agent(self, content, packet):

        new_agent = content.get("new_agent", {})
        src = new_agent.get("source_payload")

        target_uid = content.get("target_universal_id")

        if target_uid == "matrix":
            self.log("[REPLACE] ❌ Cannot target Matrix for self-replacement. Operation aborted.")
            return

        if not target_uid:
            self.log("[REPLACE] ❌ Missing 'target_universal_id'. Cannot dispatch Reaper.")
            return

        if target_uid == "matrix":
            self.log("[REPLACE] ❌ Cannot target Matrix for self-replacement. Operation aborted.")
            return

        if src:
            try:
                decoded = base64.b64decode(src["payload"]).decode()
                sha_check = hashlib.sha256(decoded.encode()).hexdigest()

                if sha_check != src["sha256"]:
                    self.log(f"[REPLACE] ❌ SHA-256 mismatch. Payload rejected.")
                    return

                agent_name = new_agent["name"]
                payload_dir = os.path.join(self.path_resolution["root_path"], "boot_payload", agent_name)
                os.makedirs(payload_dir, exist_ok=True)

                file_path = os.path.join(payload_dir, f"{agent_name}.py")
                with open(file_path, "w") as f:
                    f.write(decoded)

                self.log(f"[REPLACE] ✅ Payload source installed to {file_path}")

            except Exception as e:
                self.log(f"[REPLACE] ❌ Failed to install source payload: {e}")
                return

        if not self._validate_or_prepare_agent(new_agent):
            self.log("[REPLACE] ❌ Validation or prep failed. Replacement skipped.")
            return

        if not self._handle_replace_agent(content):
            self.log("[REPLACE] ❌ Replacement failed. Tree untouched. Aborting Reaper dispatch.")
            return

        # 🎯 Gather kill list and full field set
        kill_list = [target_uid]
        universal_ids = {target_uid: target_uid}

        # Pull optional flags from new_agent["source_payload"] or agent config
        reaper_config = new_agent.get("reaper", {})
        tombstone_comm = reaper_config.get("tombstone_comm", True)
        tombstone_pod = reaper_config.get("tombstone_pod", True)
        cleanup_die = reaper_config.get("cleanup_die", True)
        delay = reaper_config.get("delay", 2)


        # 🛠 Create reaper node with full config
        reaper_node = make_reaper_node(
            kill_list,
            universal_ids,
            tombstone_comm=tombstone_comm,
            tombstone_pod=tombstone_pod,
            delay=delay,
            cleanup_die=cleanup_die
        )

        keychain = generate_agent_keypair()
        keychain["swarm_key"] = self.swarm_key
        keychain["matrix_pub"] = self.matrix_pub
        keychain["matrix_priv"] = DUMMY_MATRIX_PRIV
        keychain["encryption_enabled"] = int(self.encryption_enabled)

        # 🛰 Deploy the bird
        self.spawn_agent_direct(reaper_node["universal_id"], reaper_node["name"], reaper_node, keychain=keychain)
        self.delegation_refresh()
        self.log(f"[REPLACE] 🧨 Reaper dispatched for {kill_list} with pod={tombstone_pod}, comm={tombstone_comm}, cleanup_die={cleanup_die}")

    def _handle_replace_agent(self, content):
        old_id = content.get("target_universal_id")
        new_node = content.get("new_agent")

        if not old_id or not new_node:
            self.log("[REPLACE] Missing required fields.")
            return False

        tp = self.load_directive(self.tree_path_dict)
        if not tp or not tp.has_node(old_id):
            self.log(f"[REPLACE] Agent '{old_id}' not found in tree.")
            return False

        parent = tp.find_parent_of(old_id)
        if not parent:
            self.log(f"[REPLACE] Could not find parent of '{old_id}'.")
            return False

        # Validate universal_id override
        new_uid = new_node.get("universal_id")
        if new_uid and new_uid != old_id:
            self.log(
                f"[REPLACE] ❌ New node contains conflicting universal_id '{new_uid}'. Must match '{old_id}' or be omitted.")
            return False

        # Update existing node in-place instead of removing
        node = tp.get_node(old_id)
        ALLOWED_FIELDS = {"name", "app", "config", "filesystem", "directives"}

        updated = False
        for key in ALLOWED_FIELDS:
            if key in new_node:
                node[key] = new_node[key]
                self.log(f"[REPLACE] ✅ Field '{key}' updated on '{old_id}'")
                updated = True

        if updated:
            # 💾 Only back up if something was actually changed
            #backup_path = self.tree_path.replace(".json", f"_backup_{int(time.time())}.json")
            #tp.save(backup_path)
            #self.log(f"[REPLACE] 💾 Tree backed up to: {backup_path}")

            # Save patched tree
            data = {"agent_tree": tp.root}
            self.save_directive(self.tree_path_dict, data)
            self.log(f"[REPLACE] 💾 Tree saved with updated agent '{old_id}'")

            # 🔁 Re-delegate the target agent
            self.delegate_tree_to_agent(old_id, self.tree_path_dict)
            self.log(f"[REPLACE] 🔁 Delegated new agent_tree to {old_id}")

            # 🔁 Re-delegate the parent who spawns this agent
            parent_id = tp.find_parent_of(old_id)
            if parent_id["universal_id"]:
                self.delegate_tree_to_agent(parent_id["universal_id"], self.tree_path_dict)
                self.log(f"[REPLACE] 🔁 Updated parent {parent_id["universal_id"]} with patched child '{old_id}'")
            else:
                self.log(f"[REPLACE] ⚠️ No parent found for '{old_id}', possible orphaned spawn chain.")
            return True
        else:
            self.log(f"[REPLACE] ⚠️ No valid fields were updated for agent '{old_id}'. Replace aborted.")

    def _validate_or_prepare_agent(self, new_agent):

        self.log(f"[DEBUG] _validate_or_prepare_agent() received: {json.dumps(new_agent, indent=2)}")

        agent_name = new_agent.get("name")
        if not agent_name:
            self.log("[REPLACE-VALIDATE] ❌ Missing agent 'name'.")
            return False

        required_fields = ["name"]
        for key in required_fields:
            if key not in new_agent:
                self.log(f"[REPLACE-VALIDATE] ❌ Missing required field: '{key}'")
                return False

        # Check standard agent path
        agent_dir = os.path.join(self.path_resolution["agent_path"], agent_name)
        entry_file = os.path.join(agent_dir, f"{agent_name}.py")

        if os.path.exists(entry_file):
            self.log(f"[REPLACE-VALIDATE] ✅ Agent source verified: {entry_file}")
            return True

        # 🧠 Check boot payload directory
        boot_payload_dir = os.path.join(self.path_resolution["root_path"], "boot_payload", agent_name)
        boot_payload_file = os.path.join(boot_payload_dir, f"{agent_name}.py")

        if os.path.exists(boot_payload_file):
            self.log(f"[REPLACE-VALIDATE] ✅ Boot-payload source verified: {boot_payload_file}")
            return True

        # Check for install payload
        payload_path = os.path.join(self.path_resolution["payload_path"], f"{agent_name}_install.pkg")
        if os.path.exists(payload_path):
            self.log(f"[REPLACE-VALIDATE] 💾 Agent source missing but install payload found: {payload_path}")
            return False

        self.log(f"[REPLACE-VALIDATE] ❌ No source and no install payload for '{agent_name}'. Replace aborted.")
        return False

    def cmd_inject(self, content, packet):

        parent = content.get("target_universal_id")
        subtree = content.get("subtree")
        if "subtree" in content:
            universal_id = content["subtree"].get("universal_id")
            agent_name = content["subtree"].get("name", "").lower()
        else:
            universal_id = content.get("universal_id")
            agent_name = content.get("name", "").lower()

        tp = self.load_directive(self.tree_path_dict)
        if not tp:
            self.log("[INJECT][ERROR] Failed to load tree.")
            return

        self.log(f"[INJECT][DEBUG] Available nodes: {list(tp.nodes.keys())}")
        if not tp.has_node(parent):
            self.log(f"[INJECT][ERROR] Parent '{parent}' not found in parsed tree.")
            return

        if not tp:
            self.log("[INJECT][ERROR] Could not load tree.")
            return

        if not tp.has_node(parent):
            self.log(f"[INJECT][ERROR] Parent node {parent} not found.")
            return

        # 🔒 Scan subtree for any node with matrix identity
        def contains_matrix_node(tree):
            if not isinstance(tree, dict):
                return False
            name = tree.get("name", "").lower()
            uid = tree.get("universal_id", "").lower()
            if name == "matrix" or uid == "matrix":
                return True
            for child in tree.get("children", []):
                if contains_matrix_node(child):
                    return True
            return False

        if subtree:
            if contains_matrix_node(subtree):
                self.log("[INJECT][BLOCKED] Subtree injection attempt includes forbidden Matrix agent.")
                return
        else:
            if agent_name == "matrix" or universal_id == "matrix":
                self.log("[INJECT][BLOCKED] Direct Matrix injection attempt denied.")
                return

        try:
            if subtree:
                try:
                    success = tp.insert_node(subtree, parent_universal_id=parent)
                except Exception as e:
                    self.log(f"[INJECT][CRASH] Insert threw: {e}")
                    return
                if not success:
                    self.log("[INJECT][ERROR] Insert failed. Rejected nodes:")
                    self.log(json.dumps(tp.rejected_subtrees, indent=2))
                    return

                inserted_uid = subtree.get("universal_id")
                attached = inserted_uid in tp.get_first_level_child_ids(parent)

                if not attached:
                    self.log(
                        f"[INJECT][WARNING] Inserted node '{inserted_uid}' NOT found under parent '{parent}' — possible orphan.")
                    return

                # NEW: Save payloads for each node in the subtree
                for node in TreeParser.flatten_tree(subtree):
                    src = node.get("source_payload")
                    name = node.get("name")
                    if src and name:
                        self._save_payload_to_boot_dir(name, src)
            else:
                delegated = content.get("delegated", [])
                filesystem = content.get("filesystem", {})
                config = content.get("config", {})
                src = content.get("source_payload")

                new_node = {
                    "name": agent_name,
                    "universal_id": universal_id,
                    "delegated": delegated,
                    "filesystem": filesystem,
                    "config": config,
                    "children": [],
                    "confirmed": time.time()
                }

                tp.insert_node(new_node, parent_universal_id=parent)
                self.log(f"[INJECT] ✅ Injected agent '{universal_id}' under '{parent}'.")

                if src:
                    self._save_payload_to_boot_dir(agent_name, src)

            data = {"agent_tree": tp.root}
            self.save_directive(self.tree_path_dict, data)

            self.delegate_tree_to_agent(parent, self.tree_path_dict)

            for agent_id in tp.get_first_level_child_ids(parent):
                self.delegate_tree_to_agent(agent_id, self.tree_path_dict)

        except Exception as e:
            self.log(f"[INJECT][CRASH] {e}")

    def cmd_shutdown_subtree(self, content, packet):
        target_id = content.get("universal_id")
        if not target_id:
            self.log("[SHUTDOWN][ERROR] Missing universal_id.")
            return

        tp = self.load_directive(self.tree_path_dict)
        if not tp:
            self.log("[SHUTDOWN][ERROR] Failed to load tree.")
            return

        ids = tp.get_subtree_nodes(target_id)
        for uid in ids:
            die_path = os.path.join(self.path_resolution["comm_path"], uid, "incoming", "die")
            os.makedirs(os.path.dirname(die_path), exist_ok=True)
            with open(die_path, "w") as f:
                f.write("☠️")
            self.log(f"[SHUTDOWN] Dropped .die for {uid}")

    def cmd_resume_subtree(self, content, packet):
        target_id = content.get("universal_id")
        if not target_id:
            self.log("[RESUME][ERROR] Missing universal_id.")
            return

        tp = self.load_directive(self.tree_path_dict)
        if not tp:
            self.log("[RESUME][ERROR] Failed to load tree.")
            return

        ids = tp.get_subtree_nodes(target_id)
        for uid in ids:
            die = os.path.join(self.path_resolution["comm_path"], uid, "incoming", "die")
            tomb = os.path.join(self.path_resolution["comm_path"], uid, "incoming", "tombstone")

            for path in [die, tomb]:
                if os.path.exists(path):
                    os.remove(path)
                    self.log(f"[RESUME] Removed {os.path.basename(path)} for {uid}")

    def _save_payload_to_boot_dir(self, agent_name, src):
        try:

            decoded = base64.b64decode(src["payload"]).decode()
            sha_check = hashlib.sha256(decoded.encode()).hexdigest()

            if sha_check != src["sha256"]:
                self.log(f"[INJECT][SHA-FAIL] {agent_name} payload hash mismatch.")
                return

            dir_path = os.path.join(self.path_resolution["root_path"], "boot_payload", agent_name)
            os.makedirs(dir_path, exist_ok=True)

            file_path = os.path.join(dir_path, f"{agent_name}.py")
            with open(file_path, "w") as f:
                f.write(decoded)

            self.log(f"[INJECT] ✅ Source code installed at {file_path}")

        except Exception as e:
            self.log(f"[INJECT][PAYLOAD-ERROR] {e}")

    #checks everyone's tree against Matrix's agent_tree_master, using a hash of the agents tree
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

                tp = self.load_directive(self.tree_path_dict)
                if not tp:
                    self.log("[VERIFY-TREE] Could not load master tree.")
                    return

                for universal_id in tp.all_universal_ids():
                    target_dir = os.path.join(self.path_resolution["comm_path"], universal_id)
                    if not os.path.isdir(target_dir):
                        continue

                    tree_path = os.path.join(target_dir, 'directive', "agent_tree.json")
                    needs_update = False

                    # Get what SHOULD be there
                    expected_subtree = tp.extract_subtree_by_id(universal_id)
                    if not expected_subtree:
                        expected_subtree = {}
                    data = {"agent_tree": expected_subtree, 'services': tp.get_service_managers(universal_id)}
                    expected_hash = hashlib.sha256(canonical_json(data).encode()).hexdigest()

                    if not os.path.exists(tree_path):
                        needs_update = True
                    else:
                        try:

                            tree_path = {
                                "path": self.path_resolution["comm_path"],
                                "address": universal_id,
                                "drop": "directive",
                                "name": "agent_tree.json"
                            }

                            lp = self.load_directive(tree_path)
                            data2 = {"agent_tree": lp.root, 'services': lp._service_manager_services}
                            current_hash = hashlib.sha256(canonical_json(data2).encode()).hexdigest()

                            if current_hash != expected_hash:
                                needs_update = True


                        except Exception as e:
                            self.log(f"[VERIFY-TREE] {universal_id} tree parse fail: {e}")
                            needs_update = True

                    if needs_update:
                        self.log(f"[VERIFY-TREE][UPDATING][HASH]{data}:{data2}")
                        self.log(f"[VERIFY-TREE][UPDATING] {universal_id} agent_tree.json update initiating.")
                        self.delegate_tree_to_agent(universal_id, self.tree_path_dict)

        except Exception as e:
            self.log(f"[VERIFY-TREE] Error: {e}")


if __name__ == "__main__":
    agent = Agent()
    agent.boot()