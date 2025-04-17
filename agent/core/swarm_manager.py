# Matrix: An AI OS System
# Copyright (c) 2025 Daniel MacDonald
# Licensed under the MIT License. See LICENSE file in project root for details.
from agent.core.tree_parser import TreeParser
from agent.core.class_lib.logging.logger import Logger
from agent.core.class_lib.file_system.util.json_safe_write import JsonSafeWrite
import os
import time
import json

class SwarmManager:
    def __init__(self, path_resolution):
        self.path_resolution = path_resolution
        self.tree_path = os.path.join(self.path_resolution['comm_path'], 'matrix', 'agent_tree_master.json')
        self.logger = Logger(self.path_resolution["comm_path_resolved"])

    def handle_injection(self, content):

        # target_permanent_id of parent of the node to be inserted, has to exist
        #   target_perm_id = content.get("target_perm_id")
        # permanent_id of node to be inserted, has to be unique
        #   perm_id = content.get("perm_id")
        # agent_name of the agent/agent to be cloned
        #   agent_name = content.get("agent_name")
        #not used
        #   delegated = content.get("delegated", [])

        subtree = {
            "permanent_id": content.get("perm_id"),
            "name": content.get("agent_name"),
            "delegated": content.get("delegated", [])
        }
        self.handle_team_injection(subtree, target_permanent_id=content.get("target_perm_id"))

    def handle_team_injection(self, subtree, target_permanent_id=None):
        tp = TreeParser.load_tree(self.tree_path)
        if not tp:
            self.logger.log("[TEAM-INJECT] Failed to load master tree.")
            return

        if not subtree or not isinstance(subtree, dict):
            self.logger.log("[TEAM-INJECT] Invalid or empty subtree.")
            return

        if not target_permanent_id:
            self.logger.log("[TEAM-INJECT] Missing target permanent_id to inject into.")
            return

        # Validate target exists
        if not tp.has_node(target_permanent_id):
            self.logger.log(f"[TEAM-INJECT][ABORT] Target node '{target_permanent_id}' not found.")
            return

        # Flatten new structure and check for conflicts
        new_nodes = TreeParser.flatten_tree(subtree)
        new_ids = [node.get("permanent_id") for node in new_nodes if node.get("permanent_id")]
        existing_ids = set(tp.get_all_nodes_flat().keys())

        conflicts = [nid for nid in new_ids if nid in existing_ids]
        if conflicts:
            self.logger.log(f"[TEAM-INJECT][ABORT] Conflict with existing nodes: {conflicts}")
            return

        if len(new_ids) != len(set(new_ids)):
            self.logger.log(f"[TEAM-INJECT][ABORT] Subtree contains duplicate permanent_ids internally.")
            return

        # Inject the entire structure under the target node
        try:
            tp.insert_node(subtree, parent_permanent_id=target_permanent_id)
            tp.save_tree(self.tree_path)
            self.logger.log(
                f"[TEAM-INJECT] Subtree injected under '{target_permanent_id}'. Root: {subtree.get('permanent_id')}")

        except Exception as e:
            self.logger.log(f"[TEAM-INJECT][ERROR] Failed to inject subtree: {e}")
            return

        # Trigger only the root node of the injected subtree — and let the chain reaction begin
        root_id = subtree.get("permanent_id")
        if root_id:
            request_path = os.path.join(self.path_resolution["comm_path"], "matrix", "incoming",
                                        f"{target_permanent_id}:_tree_slice_request.cmd")
            JsonSafeWrite.safe_write(request_path, "1")
            self.logger.log(f"[TEAM-INJECT] Slice request primed for root: {root_id}")

    def execute_resume(self, perm_id):
        comm_path = os.path.join(self.path_resolution['comm_path'], perm_id)
        die_path = os.path.join(comm_path, "incoming", "die")

        if os.path.exists(die_path):
            os.remove(die_path)
            self.log(f"[SCAVENGER] Resume signal: removed die file for {perm_id}")
            self.send_confirmation(perm_id, "resumed")
            return

        self.log(f"[SCAVENGER] No die file present for {perm_id}. Nothing to resume.")
        self.send_confirmation(perm_id, "no_action")

    def kill_subtree(self, perm_id):
        tp = TreeParser.load_tree(self.tree_path)
        if not tp or not tp.has_node(perm_id):
            self.logger.log(f"[SwarmManager][KILL] Node '{perm_id}' not found.")
            return

        nodes = [node.get("permanent_id") for node in TreeParser.flatten_tree(tp.extract_subtree_by_id(perm_id))]
        for node_id in nodes:
            die_path = os.path.join(self.path_resolution['comm_path'], node_id, "payload", "die.cmd")
            JsonSafeWrite.safe_write(die_path, "terminate")
            self.logger.log(f"[SwarmManager][KILL] Marked '{node_id}' for termination.")

        # Signal scavenger agent to begin sweep
        scav_cmd = os.path.join(self.path_resolution['comm_path'], "scavenger", "payload", f"scavenge_{perm_id}.cmd")
        JsonSafeWrite.safe_write(scav_cmd, "1")
        self.logger.log(f"[SwarmManager][KILL] Scavenger summoned for '{perm_id}' subtree cleanup.")

    def kill_agent(self, perm_id, annihilate=True):
        tp = TreeParser.load_tree(self.tree_path)
        if not tp or not tp.has_node(perm_id):
            self.logger.log(f"[SWARM][KILL] Target '{perm_id}' not found.")
            return

        flat = tp.get_all_nodes_flat()
        delegated_by = None
        scavenger_target = None

        # Walk up to parent that delegated this node
        for node_id, node in flat.items():
            if "delegated" in node and perm_id in node["delegated"]:
                delegated_by = node_id
                break

        # Scan delegated children for a scavenger agent
        if delegated_by:
            child_ids = flat.get(delegated_by, {}).get("delegated", [])
            for cid in child_ids:
                child = flat.get(cid, {})
                if child.get("agent_name") in ["scavenger"]:
                    scavenger_target = cid
                    break

        # Fallback if no scavenger found
        if not scavenger_target:
            self.logger.log(f"[SWARM][KILL] No scavenger found under '{delegated_by}', defaulting to 'scavenger-root'")
            scavenger_target = "scavenger-root"

        # Write the kill command
        cmd_file = f"scavenge_{perm_id}.cmd" if annihilate else f"kill_{perm_id}.cmd"
        path = os.path.join(self.path_resolution["comm_path"], scavenger_target, "payload", cmd_file)
        JsonSafeWrite.safe_write(path, "1")

    def kill_all_agents(self, annihilate=True):
        self.logger.log(f"[SWARM][KILL-ALL] Initiating global wipe (annihilate={annihilate})")

        from agent.core.tree_parser import TreeParser
        tp = TreeParser.load_tree(self.tree_path)
        if not tp:
            self.logger.log("[SWARM][KILL-ALL] Tree unavailable.")
            return

        for perm_id in tp.get_all_nodes_flat().keys():
            self.kill_agent(perm_id, annihilate=annihilate)

    def log(self, msg):
        print(time.strftime("[%Y-%m-%d %H:%M:%S]"), msg)

