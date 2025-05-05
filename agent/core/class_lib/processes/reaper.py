import os
import time
import signal
import json
import psutil
import re
from pathlib import Path
from agent.core.class_lib.logging.logger import Logger
from agent.core.class_lib.file_system.util.json_safe_write import JsonSafeWrite

class Reaper:
    def __init__(self, pod_root, comm_root, timeout_sec=60, logger=None):
        self.pod_root = Path(pod_root)
        self.comm_root = Path(comm_root)
        self.timeout = timeout_sec  # Max wait time for graceful shutdown

        self.tombstone_mode = True  # existing
        self.tombstone_comm = True  # existing
        self.tombstone_pod = True
        self.mission_targets = set()  # ⚡ WARP: Targets this Reaper is allowed to kill

        self.reaped = []
        self.agents = {}
        self.logger = logger if isinstance(logger, Logger) else None

    def reap_all(self):
        """
        Main reaping operation:
          1. Pass out die cookies.
          2. Wait for agents to exit gracefully.
          3. Escalate to SIGTERM or SIGKILL if necessary.
        """
        self.log_info("[REAPER][info] Initiating swarm-wide reaping operation...")

        agent_paths = list(self.pod_root.iterdir())

        # Pass out `die` cookies to signal graceful shutdown
        self.pass_out_die_cookies(agent_paths)

        # Wait for agents to stop gracefully within timeout

        shutdown_success = self.wait_for_agents_shutdown()

        if not shutdown_success:
            # Escalate if agents are still running
            self.log_info("[REAPER][warning] Some agents failed to terminate gracefully. Escalating...")
            # Find and process matching PIDs
            #matching_pids = self.find_bigbang_agents(global_id)
            self.escalate_shutdown() #matching_pids)

        self.log_info("[REAPER][info] Swarm-wide reaping operation concluded.")

    def log_info(self, message):
        """Helper function for logging with fallback to print."""
        if self.logger:
            self.logger.log(message)
        else:
            print(message)

    def pass_out_die_cookies(self, agent_paths):
        self.log_info("[REAPER][info] Distributing `die` cookies to agents...")

        for agent_path in agent_paths:
            try:
                # Load boot.json
                boot_path = os.path.join(agent_path, "boot.json")
                if not os.path.isfile(boot_path):
                    continue

                with open(boot_path, "r") as f:
                    boot_data = json.load(f)

                universal_id = boot_data.get("universal_id")
                pid = boot_data.get("pid")
                cmdline = boot_data.get("cmd", [])

                if not universal_id:
                    continue

                    # 🔥 MISSION TARGET FILTER
                if self.mission_targets and universal_id not in self.mission_targets:
                    continue  # ⚡ Skip non-targets

                comm_path = os.path.join(self.comm_root, universal_id, "incoming")
                os.makedirs(comm_path, exist_ok=True)
                die_path = os.path.join(comm_path, "die")

                JsonSafeWrite.safe_write(die_path, "terminate")

                self.log_info(f"[REAPER][info] `die` cookie distributed for {universal_id}.")

                if self.tombstone_mode:
                    if getattr(self, "tombstone_comm", True):
                        tombstone_comm_path = os.path.join(comm_path, "tombstone")
                        JsonSafeWrite.safe_write(tombstone_comm_path, "true")

                    if getattr(self, "tombstone_pod", True):
                        pod_tombstone_path = os.path.join(agent_path, "tombstone")
                        try:
                            Path(pod_tombstone_path).write_text("true")
                            self.log_info(f"[REAPER][info] Pod tombstone dropped for {universal_id}.")
                        except Exception as e:
                            self.log_info(f"[REAPER][error] Failed to drop pod tombstone for {universal_id}: {e}")

                # Track agent
                self.agents[universal_id] = {
                    "pid": pid,
                    "details": {
                        "cmd": cmdline,
                    }
                }

            except Exception as e:
                self.log_info(f"[REAPER][error] Failed to distribute `die` cookie: {e}")

    def wait_for_agents_shutdown(self, check_interval=10):

        total_wait_time = 0
        survivors = []

        while total_wait_time <= self.timeout:
            survivors.clear()

            for universal_id, agent_info in self.agents.items():


                if self.is_cmdline_still_alive(agent_info):
                    survivors.append(universal_id)

            if not survivors:
                self.log_info("[REAPER][info] All agents have exited cleanly.")
                return True  # shutdown_success = True

            self.log_info(f"[REAPER][info] Agent {universal_id} is still breathing...")

            time.sleep(check_interval)
            total_wait_time += check_interval

        self.log_info(f"[REAPER][warning] Survivors detected after timeout: {survivors}")
        return False  # shutdown_success = False

    def is_cmdline_still_alive(self, agent_info):
        """
        Check if the agent is still breathing based on stored cmdline signature.
        """
        cmd_target = agent_info.get("details", {}).get("cmd")
        if not cmd_target:
            return False

        for proc in psutil.process_iter(['cmdline']):
            try:
                if proc.info['cmdline'] == cmd_target:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return False

    def is_pid_alive(self, pid):
        """
          Checks whether a process with the given PID is alive.
          Accounts for zombie processes.
          """
        try:
            proc = psutil.Process(pid)
            if proc.status() == psutil.STATUS_ZOMBIE:
                return False  # Consider zombie processes as not alive
            return proc.is_running()
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            print(f"[WARNING] Access denied to process {pid}. Assuming it is alive.")
            return True
        except Exception as e:
            print(f"[ERROR] Unexpected error when checking PID {pid}: {e}")
            return False

    def escalate_shutdown(self):
        """
        Escalates shutdown procedure using exact cmd matching from boot.json.
        """
        for universal_id, agent_info in self.agents.items():
            try:
                cmd_target = agent_info.get("details", {}).get("cmd")
                if not cmd_target:
                    self.log_info(f"[REAPER][error] No cmdline stored for agent {universal_id}. Skipping.")
                    continue

                # Find matching PIDs
                matching_pids = []
                for proc in psutil.process_iter(['pid', 'cmdline']):
                    try:
                        if proc.info['cmdline'] == cmd_target:
                            matching_pids.append(proc.info['pid'])
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                # Kill them clean
                for pid in matching_pids:
                    os.kill(pid, signal.SIGTERM)
                    self.log_info(f"[REAPER][info] SIGTERM sent to PID {pid}. Waiting for termination...")
                    time.sleep(5)

                    if self.is_pid_alive(pid):
                        os.kill(pid, signal.SIGKILL)
                        self.log_info(f"[REAPER][info] SIGKILL sent to PID {pid}. Process forcibly terminated.")

            except Exception as e:
                self.log_info(f"[REAPER][error] Failed escalation for {universal_id}: {e}")

    def find_bigbang_agents(self, pod_root, global_id="bb:"):
        """
        Find all agents in pod_root whose boot.json command includes the global_id.
        """
        matching_agents = {}

        for uuid in os.listdir(pod_root):
            try:
                pod_path = os.path.join(pod_root, uuid)
                boot_path = os.path.join(pod_path, "boot.json")

                if not os.path.isfile(boot_path):
                    continue

                with open(boot_path, "r") as f:
                    boot_data = json.load(f)

                cmd = boot_data.get("cmd", [])
                universal_id = boot_data.get("universal_id")

                if not cmd or not universal_id:
                    continue

                # Check if global_id (like \"bb:\") is anywhere in the cmd args
                if any(global_id in part for part in cmd):
                    matching_agents[universal_id] = {
                        "uuid": uuid,
                        "cmd": cmd,
                        "pid": boot_data.get("pid")
                    }

            except Exception as e:
                self.log_info(f"[BIGBANG SCAN ERROR] {e}")

        return matching_agents

    def find_matching_pids(self, global_id):
        """
        Finds processes matching a specific `global_id`.

        :param global_id: The specific global_id to filter (e.g., "bb", "ai", "os").
        :return: List of PIDs for matching processes.
        """
        self.log_info(f"[REAPER][info] Searching for processes matching global_id '{global_id}'...")
        pattern = re.compile(rf"pod/[a-zA-Z0-9\-/]+/run\s+--job\s+{global_id}(:[a-z0-9-]+){{2,}}")
        matching_pids = []

        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmdline = proc.info['cmdline']
                if cmdline:
                    cmdline_str = " ".join(cmdline)
                    if pattern.search(cmdline_str):
                        matching_pids.append(proc.info['pid'])

            except psutil.NoSuchProcess:
                continue

        self.log_info(f"[REAPER][info] Found PIDs: {matching_pids}")
        return matching_pids
