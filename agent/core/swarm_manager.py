# Swarm Deployment Core - Matrix Agent v1.0
# Author: Daniel MacDonald & ChatGPT
# Purpose: Full-cycle team injection, validation, and error reporting

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

    def log(self, msg):
        print(time.strftime("[%Y-%m-%d %H:%M:%S]"), msg)

