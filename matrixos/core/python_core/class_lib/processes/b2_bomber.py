import os
import time
import signal
import errno
import math
import select
import psutil
from core.python_core.class_lib.file_system.util.json_safe_write import JsonSafeWrite


class ProcessIdentityUnavailable(RuntimeError):
    """A process cannot be identified safely enough to signal."""


class PinnedProcess:
    """Bind signals to the observed process, rather than a reusable PID.

    Linux pidfds make signaling atomic with respect to PID reuse. Where
    unavailable, the same psutil Process instance rechecks PID/create-time
    before signaling; that fallback cannot eliminate the final OS-level race.
    """

    def __init__(self, pid, started_at, expected_cmd=None):
        if (type(pid) is not int or pid <= 0 or type(started_at) not in (int, float)
                or not math.isfinite(started_at) or started_at <= 0):
            raise ProcessIdentityUnavailable("missing or invalid process identity")
        self.pid = pid
        self.started_at = started_at
        self.fd = None
        try:
            if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
                try:
                    self.fd = os.pidfd_open(pid, 0)
                except OSError as exc:
                    if exc.errno not in (errno.ENOSYS, errno.EINVAL):
                        raise
            self.proc = psutil.Process(pid)
            if self.proc.create_time() != started_at:
                raise ProcessIdentityUnavailable("process creation time differs")
            if expected_cmd is not None and self.proc.cmdline() != expected_cmd:
                raise ProcessIdentityUnavailable("process command changed")
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def is_alive(self):
        try:
            if self.fd is not None:
                # A pidfd becomes readable when the original task exits, even
                # if another task has already received the same numeric PID.
                poller = select.poll()
                poller.register(self.fd, select.POLLIN)
                return not bool(poller.poll(0))
            if not self.proc.is_running():
                return False
            return self.proc.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False
        except Exception:
            # Access denied and unexpected observation errors fail closed.
            return True

    def send_signal(self, signum):
        if not self.is_alive():
            return False
        if self.fd is not None:
            try:
                signal.pidfd_send_signal(self.fd, signum, None, 0)
            except ProcessLookupError:
                return False
        elif signum == signal.SIGTERM:
            self.proc.terminate()
        else:
            self.proc.send_signal(signum)
        return True

    def kill(self):
        if not self.is_alive():
            return False
        if self.fd is not None:
            try:
                signal.pidfd_send_signal(self.fd, signal.SIGKILL, None, 0)
            except ProcessLookupError:
                return False
        else:
            self.proc.kill()
        return True

class B2Bomber:
    """
    Simple 'level it' bomber:
      - write die cookie
      - wait for graceful exit (timeout)
      - SIGTERM -> short wait -> SIGKILL survivors
    """

    def __init__(self, logger=None, stagger_delay=0.1):
        self.logger = logger
        self.agents = {}
        self.stagger_delay = stagger_delay

    def log_info(self, message):
        if self.logger:
            try:
                # logger may expose .info
                self.logger.info(message)
                return
            except Exception:
                pass
        print(message)

    def pass_out_die_cookies(self, agent_list, dry_run=False):
        """
        agent_list: list of dicts with at least {'universal_id', 'comm_path', 'pod_path', 'pid'}
        Drop die cookie in /comm/{uid}/incoming/die files.
        """
        self.log_info("[B2-BOMBER][UNIVERSE-CARPET-BOMBING-COMMENCING] Distributing `die` cookies.")
        for agent in agent_list:
            try:
                comm_root = agent.get("comm_path")
                uid = agent.get("universal_id")
                pod_path = agent.get("pod_path")
                pid = agent.get("pid")

                # Track the process before filesystem work. A missing comm
                # path or failed cookie write must never make a live PID
                # invisible to shutdown verification.
                tracker_id = f"{uid or 'unknown'}:{pid or 'no-pid'}"
                self.agents[tracker_id] = {
                    "pid": pid,
                    "universal_id": uid or tracker_id,
                    "process_started_at": agent.get("process_started_at"),
                    "process_ref": None,
                    "identity_gone": False,
                    "details": {"cmd": (agent.get("details") or {}).get("cmd")}
                }
                record = self.agents[tracker_id]
                try:
                    record["process_ref"] = PinnedProcess(pid, record["process_started_at"])
                except (psutil.NoSuchProcess, ProcessLookupError):
                    record["identity_gone"] = True
                except Exception as exc:
                    record["identity_unverified"] = True
                    self.log_info(f"[B2-BOMBER][WARN] Cannot safely pin PID {pid}: {type(exc).__name__}")

                if record.get("identity_gone") or record.get("identity_unverified"):
                    self.log_info(f"[B2-BOMBER][WARN] Skipping die cookie for unverified PID {pid}")
                    continue

                if not comm_root or not uid:
                    self.log_info(f"[B2-BOMBER][SKIP] Missing comm_path/universal_id for agent: {agent}")
                    continue

                uid_dir = os.path.join(comm_root, uid)
                incoming = os.path.join(uid_dir, "incoming")
                os.makedirs(incoming, exist_ok=True)
                die_path = os.path.join(incoming, "die")

                if dry_run:
                    self.log_info(f"[B2-BOMBER][DRYRUN] Would write die -> {die_path}")
                else:
                    JsonSafeWrite.safe_write(die_path, "terminate")
                    self.log_info(f"B2-BOMBER][DROPPING-DIE-COOKIE] `die` cookie written for {uid} at {die_path}")
            except Exception as e:
                self.log_info(f"[B2-BOMBER][DROPPING-DIE-COOKIE][ERROR] Failed to distribute die cookie for {agent}: {e}")

    def is_pid_alive(self, pid):
        try:
            if not pid:
                return False
            proc = psutil.Process(pid)
            if proc.status() == psutil.STATUS_ZOMBIE:
                return False
            return proc.is_running()
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            self.log_info(f"[B2-BOMBER][IS-ALIVE][WARN] Access denied checking PID {pid}; assuming alive")
            return True
        except Exception as e:
            self.log_info(f"[B2-BOMBER][ERROR] Unexpected error checking PID {pid}: {e}")
            return True

    def _record_alive(self, record):
        if record.get("identity_gone"):
            return False
        ref = record.get("process_ref")
        if ref is not None:
            return ref.is_alive()
        # With missing identity, a numeric PID can only be used to establish
        # absence, never to authorize a signal to a possibly replaced process.
        pid = record.get("pid")
        return True if type(pid) is not int or pid <= 0 else self.is_pid_alive(pid)

    def wait_for_agents_shutdown(self, check_interval=2, timeout=10):
        """
        Wait up to `timeout` seconds for tracked agents (self.agents) to exit.
        Uses PID + optional hello.moto heartbeat if callers provide comm/uid in details (optional).
        Returns list of surviving agent dict entries (with universal_id and pid).
        """
        self.log_info(f"[B2-BOMBER] Waiting up to {timeout}s for agents to ingest die cookie.")
        deadline = time.monotonic() + max(float(timeout), 0)
        survivors = []

        # Simplest alive check: pid existence; if you want hello.moto, caller can prefilter
        run=1
        while True:
            survivors.clear()
            for tracker_id, info in list(self.agents.items()):
                pid = info.get("pid")
                uid = info.get("universal_id", tracker_id)
                if self._record_alive(info):
                    survivors.append(info)
                    self.log_info(f"[B2-BOMBER] 💣 Bombing Run {run} Agent {uid} (PID {pid}) still breathing...")
            if not survivors:
                return []
            if time.monotonic() >= deadline:
                break
            time.sleep(check_interval)
            run+=1

        # timed out — remaining survivors
        self.log_info(f"[B2-BOMBER] Timeout reached. Survivors: {[s['universal_id'] for s in survivors]}")
        return survivors

    def escalate_shutdown(self, survivors, grace_after_term=1,
                          grace_after_kill=2, dry_run=False):
        """Signal only pinned individual processes; never a shared process group."""
        if not survivors:
            return []
        active = []
        borrowed = []
        try:
            for supplied in survivors:
                record = dict(supplied)
                pid = record.get("pid")
                ref = record.get("process_ref")
                if ref is None and not record.get("identity_gone") and not record.get("identity_unverified"):
                    try:
                        ref = PinnedProcess(pid, record.get("process_started_at"))
                        record["process_ref"] = ref
                        borrowed.append(ref)
                    except (psutil.NoSuchProcess, ProcessLookupError):
                        record["identity_gone"] = True
                    except Exception as exc:
                        self.log_info(f"[B2-BOMBER][WARN] Refusing unverified PID {pid}: {type(exc).__name__}")
                if not self._record_alive(record):
                    continue
                active.append(record)
                if ref is None:
                    continue
                try:
                    if dry_run:
                        self.log_info(f"[DRYRUN] Would SIGTERM pinned PID {pid}")
                    elif ref.send_signal(signal.SIGTERM):
                        self.log_info(f"[B2-BOMBER] SIGTERM → PID {pid}")
                except (psutil.NoSuchProcess, ProcessLookupError):
                    pass
                except Exception as exc:
                    self.log_info(f"[B2-BOMBER][WARN] SIGTERM failed for PID {pid}: {type(exc).__name__}")

            if active and not dry_run:
                time.sleep(max(float(grace_after_term), 0))
            for record in active:
                ref = record.get("process_ref")
                if ref is None or not self._record_alive(record):
                    continue
                try:
                    if dry_run:
                        self.log_info(f"[DRYRUN] Would SIGKILL pinned PID {record.get('pid')}")
                    elif ref.kill():
                        self.log_info(f"[B2-BOMBER] SIGKILL → PID {record.get('pid')}")
                except (psutil.NoSuchProcess, ProcessLookupError):
                    pass
                except Exception as exc:
                    self.log_info(f"[B2-BOMBER][WARN] SIGKILL failed for PID {record.get('pid')}: {type(exc).__name__}")

            deadline = time.monotonic() + max(float(grace_after_kill), 0)
            while True:
                remaining = [record for record in active if self._record_alive(record)]
                if not remaining or dry_run or time.monotonic() >= deadline:
                    return remaining
                time.sleep(0.1)
        finally:
            for ref in borrowed:
                ref.close()

    def level_it(self, target_list, check_interval=2, timeout=30, dry_run=False):
        """
        Simplified: write die for every target, wait, then level survivors.
        target_list: list of dicts with keys 'universal_id','comm_path','pod_path','pid', 'details'
        """
        self.log_info("[B2-BOMBER] Initiating 'level it' sequence.")
        self.agents = {}
        if not target_list:
            self.log_info("[B2-BOMBER][WARN] No targets provided.")
            return True

        try:
            self.pass_out_die_cookies(target_list, dry_run=dry_run)
            survivors = self.wait_for_agents_shutdown(check_interval=check_interval, timeout=timeout)
            if survivors:
                self.log_info("[B2-BOMBER][WARNING] Survivors detected — leveling now.")
                survivors = self.escalate_shutdown(survivors, grace_after_term=1, dry_run=dry_run)
                if survivors:
                    self.log_info("[B2-BOMBER][FATAL] Unable to stop: "
                                  f"{[s['universal_id'] for s in survivors]}")
                    return False
            else:
                self.log_info("[B2-BOMBER] All targets exited cleanly.")
            self.log_info("[B2-BOMBER] Universe-wide carpet-bombing operation complete.")
            return True
        finally:
            for info in self.agents.values():
                ref = info.get("process_ref")
                if ref is not None:
                    ref.close()
