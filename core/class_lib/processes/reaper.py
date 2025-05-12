import os
import time
import signal
import json
import psutil
import re
from pathlib import Path
from core.class_lib.logging.logger import Logger
from core.class_lib.file_system.util.json_safe_write import JsonSafeWrite

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

        self.log_info("[REAPER][info] Waiting 10s for agents to ingest die cookie...")
        time.sleep(10)

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
        pid = agent_info.get("pid")
        cmd_target = agent_info.get("details", {}).get("cmd")

        if not cmd_target or not pid:
            return False
        try:
            proc = psutil.Process(pid)
            if proc.status() == psutil.STATUS_ZOMBIE:
                return False
            if proc.cmdline() == cmd_target:
                return proc.is_running()
            return False
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            return True
        except Exception as e:
            print(f"[REAPER][ERROR] PID check failed: {e}")
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
        Immediately SIGTERM all matching PIDs. If still alive after short delay, SIGKILL.
        """
        self.log_info("[ESCALATE] Sending SIGTERM to all tracked agents...")

        active_pids = {}

        for universal_id, agent_info in self.agents.items():
            cmd_target = agent_info.get("details", {}).get("cmd")
            if not cmd_target:
                continue

            for proc in psutil.process_iter(['pid', 'cmdline']):
                try:
                    if proc.info['cmdline'] == cmd_target:
                        pid = proc.info['pid']
                        active_pids[universal_id] = pid
                        os.kill(pid, signal.SIGTERM)
                        self.log_info(f"[REAPER] SIGTERM → {universal_id} (PID {pid})")
                except Exception as e:
                    self.log_info(f"[REAPER] Error sending SIGTERM to {universal_id}: {e}")

        # Short wait for them to acknowledge and self-terminate
        self.log_info("[ESCALATE] Waiting 1sec before SIGKILL...")
        time.sleep(1)

        # Kill any survivors
        for uid, pid in active_pids.items():
            if self.is_pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                    self.log_info(f"[REAPER] SIGKILL → {uid} (PID {pid})")
                except Exception as e:
                    self.log_info(f"[REAPER] Failed to SIGKILL {uid}: {e}")


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

    #kills whole universe
    def kill_universe_processes(self, global_id, passes=3):
        import re

        self.log_info(f"[MEM-KILL] Scanning memory for --job {global_id}:...")

        pattern = re.compile(rf"--job\s+{re.escape(global_id)}(:[a-z0-9_\-]+){{2,}}")
        survivors = set()

        for i in range(passes):
            self.log_info(f"[MEM-KILL] 🔁 Pass {i + 1} — sweeping for live agents...")

            for proc in psutil.process_iter(['pid', 'cmdline']):
                try:
                    cmdline = " ".join(proc.info['cmdline'])
                    if pattern.search(cmdline):
                        pid = proc.info['pid']
                        if pid in survivors:
                            continue  # Already hit this one

                        try:
                            os.kill(pid, signal.SIGTERM)
                            self.log_info(f"[MEM-KILL] SIGTERM → PID {pid}")
                        except ProcessLookupError:
                            continue

                        survivors.add(pid)
                except Exception as e:
                    self.log_info(f"[MEM-KILL][WARN] Scan error: {e}")

            time.sleep(3)  # short delay for agents to shut down

            # MIRV-heavy: SIGKILL phase
            for pid in list(survivors):
                try:
                    if psutil.pid_exists(pid):
                        os.kill(pid, signal.SIGKILL)
                        self.log_info(f"[MEM-KILL] SIGKILL → PID {pid}")
                    survivors.discard(pid)
                except Exception as e:
                    self.log_info(f"[MEM-KILL][FAIL] Could not SIGKILL PID {pid}: {e}")

            if not survivors:
                self.log_info(f"[MEM-KILL] ✅ All agents neutralized on pass {i + 1}.")
                return

        if survivors:
            self.log_info(f"[MEM-KILL] ⚠️ Survivors remain after {passes} passes: {survivors}")


    def drop_die_tokens_from_tree(self, tree_node):
        """
        Recursively walks a directive tree and drops `die` files into /comm/{uid}/incoming/
        """
        uid = tree_node.get("universal_id")
        if uid:
            inbox = os.path.join(self.comm_root, uid, "incoming")
            os.makedirs(inbox, exist_ok=True)
            die_path = os.path.join(inbox, "die")
            with open(die_path, "w") as f:
                f.write("terminate")
            self.log_info(f"[REAPER] Dropped die token for: {uid}")

        for child in tree_node.get("children", []):
            self.drop_die_tokens_from_tree(child)