import os

from pathlib import Path
from core.python_core.class_lib.processes.reaper import Reaper
from core.python_core.reuse_cleanup import validate_agent_ids

class DefaultLogger:
    def log(self, message):
        print(message)

class ReaperUniversalHandler:
    def __init__(self, pod_root, comm_root, logger=None, *, lifecycle_base=None,
                 lifecycle_universe=None, lifecycle_generation=None):
        self.pod_root = Path(pod_root)
        self.comm_root = Path(comm_root)
        self.logger = logger or DefaultLogger()
        self.lifecycle_base = lifecycle_base
        self.lifecycle_universe = lifecycle_universe
        self.lifecycle_generation = lifecycle_generation

    def process_all_universal_ids(self, universal_ids, tombstone_mode=False, wait_seconds=20, tombstone_comm=True, tombstone_pod=True):
        reaper = Reaper(self.pod_root, self.comm_root, timeout_sec=wait_seconds,
                        logger=self.logger.log, lifecycle_base=self.lifecycle_base,
                        lifecycle_universe=self.lifecycle_universe,
                        lifecycle_generation=self.lifecycle_generation)
        try:
            validate_agent_ids(universal_ids)
            with reaper.lifecycle_guard():
                return self._process_locked(reaper, universal_ids, tombstone_mode,
                                            wait_seconds, tombstone_comm, tombstone_pod)
        except Exception as exc:
            self.logger.log(f"[REAPER-HANDLER][ERROR] Lifecycle fencing failed: {exc}")
            return False

    def _process_locked(self, reaper, universal_ids, tombstone_mode, wait_seconds, tombstone_comm, tombstone_pod):
        self.logger.log("[REAPER-HANDLER] Starting universal_id reaping...")

        reaper.mission_targets = set(universal_ids)
        shutdown_success = False
        incomplete = False
        try:
            agent_paths = []
            for name in os.listdir(reaper._pod_fd):
                pod_dir = self.pod_root / name
                try:
                    data = reaper._read_boot_record(name)
                    if not isinstance(data, dict) or not isinstance(data.get("universal_id"), str) or not data["universal_id"]:
                        raise ValueError("missing or invalid universal_id")
                    validate_agent_ids((data["universal_id"],))
                    if data.get("universal_id") in universal_ids:
                        agent_paths.append(pod_dir)
                except Exception as e:
                    self.logger.log(f"[REAPER-HANDLER][ERROR] Reading {pod_dir / 'boot.json'}: {e}")
                    incomplete = True

            if not agent_paths:
                self.logger.log("[REAPER-HANDLER][WARNING] No matching agents found for universal_ids.")

            else:

                reaper.tombstone_mode = tombstone_mode
                reaper.tombstone_comm = tombstone_comm
                reaper.tombstone_pod = tombstone_pod

                reaper._pass_out_die_cookies_locked(agent_paths)
                self.logger.log(f"[REAPER-HANDLER] Waiting {wait_seconds} seconds for shutdown...")
                shutdown_success = reaper.wait_for_agents_shutdown()
                if not shutdown_success:
                    self.logger.log("[REAPER-HANDLER][WARNING] Agents survived initial shutdown. Escalating...")
                    shutdown_success = not bool(reaper._escalate_shutdown_locked())
        except Exception as e:
            print(f"[REAPER-UNIVERSAL-HANDLER][ERROR] no agents found in path: {e}")
            incomplete = True
        finally:
            for info in reaper.agents.values():
                ref = info.get("process_ref")
                if ref is not None:
                    ref.close()

        shutdown_success = shutdown_success and not incomplete
        if shutdown_success:
            self.logger.log("[REAPER-HANDLER] Universal_id reaping operation complete.")
        else:
            self.logger.log("[REAPER-HANDLER][WARNING] Reaping incomplete or unverifiable.")
        return shutdown_success
