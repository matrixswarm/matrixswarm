import os
import time
import signal
import json
import psutil
import re
from pathlib import Path
from agent.core.class_lib.logging.logger import Logger


class Reaper:
    def __init__(self, pod_root, comm_root, timeout_sec=300, logger=None):
        self.pod_root = Path(pod_root)
        self.comm_root = Path(comm_root)
        self.timeout = timeout_sec  # Max wait time for graceful shutdown
        self.reaped = []
        self.agents = {}
        self.logger = logger if isinstance(logger, Logger) else None


    def reap_all(self, global_id):
        """
        Main reaping operation:
          1. Pass out die cookies.
          2. Wait for agents to exit gracefully.
          3. Escalate to SIGTERM or SIGKILL if necessary.
        """
        self.log_info("[REAPER][info] Initiating swarm-wide reaping operation...")

        # Pass out `die` cookies to signal graceful shutdown
        self.pass_out_die_cookies()

        # Wait for agents to stop gracefully within timeout
        shutdown_success = self.wait_for_agents_shutdown()

        if not shutdown_success:
            # Escalate if agents are still running
            self.log_info("[REAPER][warning] Some agents failed to terminate gracefully. Escalating...")
            self.escalate_shutdown(global_id)

        self.log_info("[REAPER][info] Swarm-wide reaping operation concluded.")

    def log_info(self, message):
        """Helper function for logging with fallback to print."""
        if self.logger:
            self.logger.log(message)
        else:
            print(message)

    def pass_out_die_cookies(self):
        """
        Loops through all agents under pod/ directory, creates the `die` cookie
        in each `comm/{perm_id}/incoming`, and asks agents to terminate gracefully.
        """
        self.log_info("[REAPER][info] Distributing `die` cookies to all agents...")

        for agent_path in self.pod_root.iterdir():
            try:
                # Locate boot.json to extract agent details
                boot_path = agent_path / "boot.json"
                if not boot_path.is_file():
                    continue

                with open(boot_path, "r") as f:
                    boot_data = json.load(f)

                perm_id = boot_data.get("permanent_id")
                pid = boot_data.get("pid")

                if perm_id:
                    self.agents[perm_id] = {"details": boot_data, "pid": pid}

                    # Create comm/{perm_id}/incoming if not exists and drop `die` cookie
                    comm_path = self.comm_root / perm_id / "incoming"
                    comm_path.mkdir(parents=True, exist_ok=True)
                    die_cookie = comm_path / "die"
                    with open(die_cookie, "w") as cookie_file:
                        json.dump({"cmd": "die", "force": False}, cookie_file)

                    self.log_info(f"[REAPER][info] `die` cookie distributed for {perm_id}.")

            except Exception as e:
                self.log_info(f"[REAPER][error] Failed to distribute `die` cookie: {e}")


    def wait_for_agents_shutdown(self, check_interval=10):
        """
        Waits for agents registered in `self.agents` to shut down gracefully.

        :param check_interval: Time in seconds between retries.
        :return: True if all agents shut down successfully, False otherwise.
        """
        total_wait_time = 0

        while total_wait_time <= self.timeout:
            all_stopped = True

            for perm_id, agent_info in self.agents.items():
                pid = agent_info.get("pid")
                if pid and psutil.pid_exists(pid):
                    self.log_info(f"[REAPER][info] Agent {perm_id} (PID: {pid}) is still running...")
                    all_stopped = False

            if all_stopped:
                self.log_info("[REAPER][info] All agents have exited cleanly.")
                return True

            time.sleep(check_interval)
            total_wait_time += check_interval

        return False

    def escalate_shutdown(self, global_id):
        """
        Escalates shutdown procedure: sends SIGTERM and then SIGKILL if agents fail to terminate.
        :param global_id: The global namespace to narrow down active relevant processes.
        """
        # Find and process matching PIDs
        matching_pids = self.find_matching_pids(global_id)

        for pid in matching_pids:
            try:
                # Send SIGTERM first
                os.kill(pid, signal.SIGTERM)
                self.log_info(f"[REAPER][info] SIGTERM sent to PID {pid}. Waiting for termination...")

                # Wait briefly for termination
                time.sleep(5)

                if psutil.pid_exists(pid):
                    # Forcefully kill if it didn't terminate
                    os.kill(pid, signal.SIGKILL)
                    self.log_info(f"[REAPER][info] SIGKILL sent to PID {pid}. Process forcibly terminated.")

            except Exception as e:
                self.log_info(f"[REAPER][error] Failed to terminate PID {pid}: {e}")

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
