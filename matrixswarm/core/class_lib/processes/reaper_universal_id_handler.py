import json

from pathlib import Path
from core.class_lib.processes.reaper import Reaper

class ReaperUniversalHandler:
    def __init__(self, pod_root, comm_root, logger=None):
        self.pod_root = Path(pod_root)
        self.comm_root = Path(comm_root)
        self.logger = logger or self.default_logger

    def default_logger(self, message):
        print(message)

    def process_all_universal_ids(self, universal_ids, tombstone_mode=False, wait_seconds=20, tombstone_comm=True, tombstone_pod=True):

        self.logger.log("[REAPER-HANDLER] Starting universal_id reaping...")

        agent_paths = []
        for pod_dir in self.pod_root.iterdir():
            boot_file = pod_dir / "boot.json"
            if not boot_file.exists():
                continue
            try:
                with open(boot_file, "r") as f:
                    data = json.load(f)
                if data.get("universal_id") in universal_ids:
                    agent_paths.append(pod_dir)
            except Exception as e:
                self.logger.log(f"[REAPER-HANDLER][ERROR] Reading {boot_file}: {e}")

        if not agent_paths:
            self.logger.log("[REAPER-HANDLER][WARNING] No matching agents found for universal_ids.")
            return

        reaper = Reaper(self.pod_root, self.comm_root, timeout_sec=wait_seconds, logger=self.logger.log)
        reaper.tombstone_mode = tombstone_mode
        reaper.tombstone_comm = tombstone_comm
        reaper.tombstone_pod = tombstone_pod

        reaper.mission_targets = set(universal_ids)

        reaper.pass_out_die_cookies(agent_paths)

        self.logger.log(f"[REAPER-HANDLER] Waiting {wait_seconds} seconds for shutdown...")

        shutdown_success = reaper.wait_for_agents_shutdown()

        if not shutdown_success:
            self.logger.log("[REAPER-HANDLER][WARNING] Agents survived initial shutdown. Escalating...")
            reaper.escalate_shutdown()

        self.logger.log("[REAPER-HANDLER] Universal_id reaping operation complete.")