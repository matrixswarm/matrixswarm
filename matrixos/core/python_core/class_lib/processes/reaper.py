import os
import time
import signal
import json
import psutil
import re
from contextlib import contextmanager, ExitStack
from pathlib import Path
import stat
from core.python_core.class_lib.logging.logger import Logger
from core.python_core.class_lib.processes.b2_bomber import B2Bomber, PinnedProcess
from core.python_core.lifecycle_fence import LifecycleFence, LifecycleError, GENERATION_ENV
from core.python_core.reuse_cleanup import validate_agent_ids
from core.python_core.safe_paths import child_directory, open_base, open_beneath, write_file_at


def _matches_job(cmdline, job_id):
    """Match a complete job label, never a different universe's prefix."""
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}(?::[A-Za-z0-9_-]+)?", job_id):
        return False
    if not isinstance(cmdline, (list, tuple)):
        return False
    for index, value in enumerate(cmdline):
        if value == "--job" and index + 1 < len(cmdline):
            actual = cmdline[index + 1]
        elif isinstance(value, str) and value.startswith("--job="):
            actual = value[6:]
        else:
            continue
        if not isinstance(actual, str):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}(?::[A-Za-z0-9_-]+)?", actual):
            continue
        if actual == job_id or (":" not in job_id and actual.startswith(job_id + ":")):
            return True
    return False

class Reaper:
    def __init__(self, pod_root, comm_root, timeout_sec=60, logger=None, *,
                 lifecycle_base=None, lifecycle_universe=None, lifecycle_generation=None):
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
        self.lifecycle_base = lifecycle_base
        self.lifecycle_universe = lifecycle_universe
        self.lifecycle_generation = lifecycle_generation or os.environ.get(GENERATION_ENV)
        self._pod_fd = None
        self._comm_fd = None

    @contextmanager
    def lifecycle_guard(self):
        """Fence targeted shutdown against boot and concurrent agent spawns."""
        if not self.lifecycle_base or not self.lifecycle_universe or not self.lifecycle_generation:
            raise LifecycleError("Targeted reaping requires an explicit universe and lifecycle generation")
        fence = LifecycleFence(self.lifecycle_base, self.lifecycle_universe)
        with fence.exclusive(expected_generation=self.lifecycle_generation):
            state = fence.read_state()
            boot = Path(self.lifecycle_base).absolute() / "universes" / "runtime" / self.lifecycle_universe / state["boot_id"]
            if self.pod_root.absolute() != boot / "pod" or self.comm_root.absolute() != boot / "comm":
                raise LifecycleError("Targeted reaper paths do not match the active universe boot")
            # Both roots stay under one opened boot directory throughout the
            # operation, so an ancestor rename cannot redirect later writes.
            with ExitStack() as stack:
                root = open_base(Path(self.lifecycle_base).absolute())
                stack.callback(os.close, root)
                for component in ("universes", "runtime"):
                    root = stack.enter_context(child_directory(root, component, traverse_only=True))
                for component in (self.lifecycle_universe, state["boot_id"]):
                    root = stack.enter_context(child_directory(root, component))
                try:
                    self._pod_fd = stack.enter_context(child_directory(root, "pod"))
                    self._comm_fd = stack.enter_context(child_directory(root, "comm"))
                    yield
                finally:
                    self._pod_fd = None
                    self._comm_fd = None

    def reap_all(self):
        with self.lifecycle_guard():
            return self._reap_all_locked()

    def _reap_all_locked(self):
        """
        Main reaping operation:
          1. Pass out die cookies.
          2. Wait for agents to exit gracefully.
          3. Escalate to SIGTERM or SIGKILL if necessary.
        """
        self.log_info("[REAPER][info] Initiating swarm-wide reaping operation...")

        try:
            agent_paths = [self.pod_root / name for name in os.listdir(self._pod_fd)]
            self._pass_out_die_cookies_locked(agent_paths)
            success = self.wait_for_agents_shutdown()
            if not success:
                self.log_info("[REAPER][warning] Some agents failed to terminate gracefully. Escalating...")
                success = not bool(self._escalate_shutdown_locked())
            if success:
                self.log_info("[REAPER][info] Swarm-wide reaping operation concluded.")
            else:
                self.log_info("[REAPER][warning] Reaping remains incomplete or unverifiable.")
            return success
        finally:
            for record in self.agents.values():
                ref = record.get("process_ref")
                if ref is not None:
                    ref.close()

    def log_info(self, message):
        """Helper function for logging with fallback to print."""
        if self.logger:
            self.logger.log(message)
        else:
            print(message)
            #print(traceback.format_exc())

    def pass_out_die_cookies(self, agent_paths):
        with self.lifecycle_guard():
            return self._pass_out_die_cookies_locked(agent_paths)

    def _pass_out_die_cookies_locked(self, agent_paths):
        self.log_info("[REAPER][info] Distributing `die` cookies to agents...")
        if self._pod_fd is None or self._comm_fd is None:
            raise LifecycleError("Targeted reaper directories are not anchored")

        for agent_path in agent_paths:
            record = None
            try:
                agent_path = Path(agent_path)
                if agent_path.absolute().parent != self.pod_root.absolute():
                    raise ValueError("Pod path is not a direct, non-link child of the active pod root")
                boot_data = self._read_boot_record(agent_path.name)

                universal_id = boot_data.get("universal_id")
                pid = boot_data.get("pid")
                cmdline = boot_data.get("cmd", [])

                if not universal_id:
                    self.agents[f"unverified:{agent_path}"] = {"pid": None, "universal_id": str(agent_path), "identity_unverified": True}
                    continue
                validate_agent_ids((universal_id,))

                    # 🔥 MISSION TARGET FILTER
                if self.mission_targets and universal_id not in self.mission_targets:
                    continue  # ⚡ Skip non-targets

                if self.lifecycle_universe and not _matches_job(cmdline, f"{self.lifecycle_universe}:{universal_id}"):
                    raise ValueError("Boot record does not identify a job in the fenced universe")

                record = {"pid": pid, "universal_id": universal_id,
                          "process_started_at": boot_data.get("process_started_at"),
                          "process_ref": None, "identity_gone": False,
                          "details": {"cmd": cmdline}}
                self.agents[f"{universal_id}:{pid}:{agent_path}"] = record
                try:
                    record["process_ref"] = PinnedProcess(pid, record["process_started_at"], expected_cmd=cmdline)
                except (psutil.NoSuchProcess, ProcessLookupError):
                    record["identity_gone"] = True
                except Exception as exc:
                    record["identity_unverified"] = True
                    self.log_info(f"[REAPER][WARN] Cannot safely pin PID {pid}: {type(exc).__name__}")

                if record.get("identity_gone") or record.get("identity_unverified"):
                    self.log_info(f"[REAPER][WARN] Skipping die cookie for unverified PID {pid}")
                    continue

                with child_directory(self._comm_fd, universal_id, create=True) as agent_fd:
                    with child_directory(agent_fd, "incoming", create=True) as incoming_fd:
                        write_file_at(incoming_fd, "die", json.dumps("terminate").encode())
                        if self.tombstone_mode and getattr(self, "tombstone_comm", True):
                            self._write_tombstone_if_missing(incoming_fd)

                self.log_info(f"[REAPER][info] `die` cookie distributed for {universal_id}.")

                if self.tombstone_mode:

                    # Drop tombstone in pod path if it doesn't already exist
                    if getattr(self, "tombstone_pod", True):
                        with child_directory(self._pod_fd, agent_path.name) as pod_fd:
                            self._write_tombstone_if_missing(pod_fd, json_encoded=False)

            except Exception as e:
                if record is not None:
                    ref = record.get("process_ref")
                    if ref is not None:
                        ref.close()
                    record["process_ref"] = None
                    record["identity_unverified"] = True
                self.agents[f"unverified:{agent_path}"] = {"pid": None, "universal_id": str(agent_path), "identity_unverified": True}
                self.log_info(f"[REAPER][error] Failed to distribute `die` cookie: {e}")

    def _read_boot_record(self, pod_name):
        if self._pod_fd is None:
            raise LifecycleError("Targeted reaper pod directory is not anchored")
        with child_directory(self._pod_fd, pod_name) as pod_fd:
            fd = open_beneath(pod_fd, "boot.json", os.O_RDONLY | os.O_NONBLOCK)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("Unsafe boot record")
                with os.fdopen(fd, "rb") as stream:
                    fd = -1
                    contents = stream.read(1024 * 1024 + 1)
                if len(contents) > 1024 * 1024:
                    raise ValueError("Boot record too large")
                data = json.loads(contents)
                if not isinstance(data, dict):
                    raise ValueError("Invalid boot record")
                return data
            finally:
                if fd >= 0:
                    os.close(fd)

    @staticmethod
    def _write_tombstone_if_missing(directory_fd, *, json_encoded=True):
        contents = json.dumps("true").encode() if json_encoded else b"true"
        try:
            fd = open_beneath(directory_fd, "tombstone", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            fd = open_beneath(directory_fd, "tombstone", os.O_PATH | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("Unsafe tombstone")
            finally:
                os.close(fd)
            return
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)

    def wait_for_agents_shutdown(self, check_interval=2):

        self.log_info("[REAPER][info] Waiting 10s for agents to ingest die cookie...")

        total_wait_time = 0
        survivors = []

        while total_wait_time <= self.timeout:
            survivors.clear()

            for universal_id, agent_info in self.agents.items():

                if self.is_cmdline_still_alive(agent_info):
                    survivors.append(universal_id)
                    self.log_info(f"[REAPER][info] Agent {universal_id} is still breathing...")

            if not survivors:
                self.log_info("[REAPER][info] All agents have exited cleanly.")
                return True  # shutdown_success = True

            time.sleep(check_interval)
            total_wait_time += check_interval

        self.log_info(f"[REAPER][warning] Survivors detected after timeout: {survivors}")
        return False  # shutdown_success = False

    def is_cmdline_still_alive(self, agent_info):
        pid = agent_info.get("pid")
        cmd_target = agent_info.get("details", {}).get("cmd")

        if agent_info.get("identity_gone"):
            return False
        ref = agent_info.get("process_ref")
        if ref is not None:
            return ref.is_alive()
        if not pid:
            return True
        try:
            proc = psutil.Process(pid)
            if proc.status() == psutil.STATUS_ZOMBIE:
                return False
            if cmd_target and proc.cmdline() == cmd_target:
                return proc.is_running()
            # Without a trusted creation time, PID existence is not proof of
            # the original process, nor proof that it is safe to proceed.
            return True
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            return True
        except Exception as e:
            print(f"[REAPER][ERROR] PID check failed: {e}")
            return True

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
            return True

    def escalate_shutdown(self):
        with self.lifecycle_guard():
            return self._escalate_shutdown_locked()

    def _escalate_shutdown_locked(self):
        """Escalate only processes pinned to their original creation time."""
        bomber = B2Bomber()
        bomber.log_info = self.log_info
        records = [dict(info) for info in self.agents.values()]
        remaining = bomber.escalate_shutdown(records)
        if remaining:
            self.log_info("[REAPER][WARN] Unverified or surviving processes remain; no unsafe PID signaling was attempted.")
        return remaining

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

                with open(boot_path, "r", encoding="utf-8") as f:
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
        """Find whole job labels, not a prefix of another universe name."""
        matching = []
        for proc in psutil.process_iter(['pid', 'cmdline']):
            try:
                if _matches_job(proc.info.get('cmdline'), global_id):
                    matching.append(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return matching

    def kill_universe_processes(self, global_id, passes=3):
        with self.lifecycle_guard():
            if global_id != self.lifecycle_universe and not global_id.startswith(self.lifecycle_universe + ":"):
                raise LifecycleError("Targeted job does not belong to the fenced universe")
            return self._kill_universe_processes_locked(global_id, passes)

    def _kill_universe_processes_locked(self, global_id, passes=3):
        """Stop exact job matches using process identities captured at scan."""
        bomber = B2Bomber()
        bomber.log_info = self.log_info
        for _ in range(passes):
            records = []
            try:
                for proc in psutil.process_iter(['pid', 'cmdline', 'create_time']):
                    try:
                        cmdline = proc.info.get('cmdline')
                        if not _matches_job(cmdline, global_id):
                            continue
                        pid = proc.info['pid']
                        started_at = proc.info.get('create_time')
                        try:
                            ref = PinnedProcess(pid, started_at, expected_cmd=cmdline)
                        except (psutil.NoSuchProcess, ProcessLookupError):
                            continue
                        except Exception as exc:
                            self.log_info(f"[REAPER][WARN] Cannot safely pin PID {pid}: {type(exc).__name__}")
                            records.append({"pid": pid, "universal_id": global_id,
                                            "process_started_at": None, "process_ref": None})
                            continue
                        records.append({"pid": pid, "universal_id": global_id,
                                        "process_started_at": started_at, "process_ref": ref})
                    except psutil.NoSuchProcess:
                        continue
                    except psutil.AccessDenied:
                        records.append({'pid': None, 'universal_id': global_id, 'identity_unverified': True})
                if not records:
                    return True
                remaining = bomber.escalate_shutdown(records, grace_after_term=3, grace_after_kill=2)
                if remaining:
                    self.log_info("[REAPER][WARN] Unverified or surviving processes remain")
                    return False
            finally:
                for record in records:
                    ref = record.get('process_ref')
                    if ref is not None:
                        ref.close()
        return not bool(self.find_matching_pids(global_id))

    def drop_die_tokens_from_tree(self, tree_node):
        with self.lifecycle_guard():
            self._validate_tree_ids(tree_node)
            return self._drop_die_tokens_from_tree_locked(tree_node)

    @staticmethod
    def _validate_tree_ids(tree_node):
        if not isinstance(tree_node, dict):
            raise LifecycleError("Invalid target tree")
        uid = tree_node.get("universal_id")
        if uid is not None:
            validate_agent_ids((uid,))
        children = tree_node.get("children", [])
        if not isinstance(children, list):
            raise LifecycleError("Invalid target tree children")
        for child in children:
            Reaper._validate_tree_ids(child)

    def _drop_die_tokens_from_tree_locked(self, tree_node):
        """
        Recursively walks a directive tree and drops `die` files into /comm/{uid}/incoming/
        """
        uid = tree_node.get("universal_id")
        if uid:
            with child_directory(self._comm_fd, uid, create=True) as agent_fd:
                with child_directory(agent_fd, "incoming", create=True) as incoming_fd:
                    write_file_at(incoming_fd, "die", b"terminate")
            self.log_info(f"[REAPER] Dropped die token for: {uid}")

        for child in tree_node.get("children", []):
            self._drop_die_tokens_from_tree_locked(child)
