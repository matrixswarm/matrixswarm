"""Fenced, identity-checked shutdown of agents in the active universe."""
import json
import hashlib
import os
from pathlib import Path
import re
import secrets
import signal
import sys
import threading
import time
from contextlib import contextmanager

import psutil

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

from core.python_core.boot_agent import BootAgent
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from core.python_core.class_lib.processes.b2_bomber import PinnedProcess
from core.python_core.class_lib.processes.reaper import Reaper, _matches_job
from core.python_core.reuse_cleanup import _remove_contents, _tree_preflight, validate_agent_ids
from core.python_core.safe_paths import child_directory, write_file_at
from core.python_core.reap_revision import read_reap_authorization


class Agent(BootAgent):
    def __init__(self):
        super().__init__()
        self._authorization_lock = threading.Lock()
        self._authorization_pending = {}
        self._authorization_inflight = set()
        self._emit_beacon = self.check_for_thread_poke("reaper", timeout=30, emit_to_file_interval=10)

    def cmd_reap_agents(self, content, packet, identity: IdentityObject = None):
        if not self._verified_matrix(identity):
            return
        if not isinstance(content, dict) or not isinstance(content.get("targets"), list):
            self.log("[REAPER] Invalid target list.", level="ERROR")
            return
        seen = set()
        for target in content["targets"]:
            if not isinstance(target, dict):
                continue
            uid, stage, transaction_id = target.get("universal_id"), target.get("op_stage"), target.get("transaction_id")
            if (not isinstance(uid, str) or not isinstance(stage, str)
                    or not isinstance(transaction_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", transaction_id)
                    or (uid, stage, transaction_id) in seen):
                continue
            seen.add((uid, stage, transaction_id))
            try:
                validate_agent_ids((uid,))
                if uid in (self.command_line_args.get("universal_id"), self.get_matrix_universal_id()):
                    raise ValueError("Refusing to reap Matrix or Reaper")
                self._request_authorization(uid, stage, transaction_id)
            except Exception as exc:
                self.log("[REAPER] Target operation failed.", error=exc, level="ERROR")
                self._report_to_matrix(uid, stage, False, transaction_id=transaction_id, error=str(exc))

    def _verified_matrix(self, identity):
        return (isinstance(identity, IdentityObject) and identity.has_verified_identity()
                and identity.get_sender_uid() == self.get_matrix_universal_id())

    def _request_authorization(self, uid, stage, transaction_id):
        nonce = secrets.token_hex(32)
        key = (uid, stage, transaction_id)
        with self._authorization_lock:
            if key in self._authorization_inflight or any(value["key"] == key for value in self._authorization_pending.values()):
                return
            if len(self._authorization_pending) >= 256:
                raise RuntimeError("Too many pending Reaper authorization requests")
            timer = threading.Timer(30, self._authorization_timeout, args=(nonce,))
            timer.daemon = True
            self._authorization_pending[nonce] = {"key": key, "deadline": time.monotonic() + 30, "timer": timer}
            timer.start()
        try:
            packet = self.get_delivery_packet("standard.command.packet")
            packet.set_data({"handler": "cmd_reap_authorize", "content": {"universal_id": uid,
                             "stage": stage, "transaction_id": transaction_id, "nonce": nonce}})
            if not self.pass_packet(packet, self.get_matrix_universal_id()):
                raise RuntimeError("Could not send Reaper authorization challenge")
        except Exception:
            with self._authorization_lock:
                pending = self._authorization_pending.pop(nonce, None)
            if pending:
                pending["timer"].cancel()
            raise

    def _authorization_timeout(self, nonce):
        with self._authorization_lock:
            pending = self._authorization_pending.pop(nonce, None)
        if pending:
            uid, stage, transaction_id = pending["key"]
            self._report_to_matrix(uid, stage, False, transaction_id=transaction_id,
                                   error="Matrix did not authorize this operation in time")

    def cmd_reap_authorization(self, content, packet, identity: IdentityObject = None):
        """Consume a single fresh, Matrix-signed response before acting."""
        if not self._verified_matrix(identity) or not isinstance(content, dict):
            return
        nonce = content.get("nonce")
        if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{64}", nonce):
            return
        with self._authorization_lock:
            pending = self._authorization_pending.get(nonce)
            if not pending or pending["key"] != (content.get("universal_id"), content.get("stage"), content.get("transaction_id")):
                return
            pending = self._authorization_pending.pop(nonce)
            self._authorization_inflight.add(pending["key"])
        pending["timer"].cancel()
        uid, stage, transaction_id = pending["key"]
        if time.monotonic() >= pending["deadline"] or content.get("authorized") is not True:
            with self._authorization_lock:
                self._authorization_inflight.discard(pending["key"])
            self._report_to_matrix(uid, stage, False, transaction_id=transaction_id,
                                   error="Matrix authorization was stale or refused")
            return
        try:
            snapshot = self._validate_target_snapshot(stage, content.get("target_snapshot"))
            revision = content.get("revision")
            if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{64}", revision):
                raise ValueError("Invalid Matrix authorization revision")
            worker = threading.Thread(target=self._execute_authorized,
                                      args=(uid, stage, transaction_id, snapshot, revision), daemon=True)
            worker.start()
        except Exception as exc:
            with self._authorization_lock:
                self._authorization_inflight.discard(pending["key"])
            self._report_to_matrix(uid, stage, False, transaction_id=transaction_id, error=str(exc))

    def _execute_authorized(self, uid, stage, transaction_id, target_snapshot, revision):
        try:
            with self._fenced_reaper() as reaper:
                self._verify_committed_authorization(reaper, uid, stage, transaction_id, target_snapshot, revision)
                state, extra = self._run_stage(reaper, uid, stage, target_snapshot)
            self._report_to_matrix(uid, stage, True, transaction_id=transaction_id, extra={"state": state, **extra})
        except Exception as exc:
            self.log("[REAPER] Target operation failed.", error=exc, level="ERROR")
            self._report_to_matrix(uid, stage, False, transaction_id=transaction_id, error=str(exc))
        finally:
            with self._authorization_lock:
                self._authorization_inflight.discard((uid, stage, transaction_id))

    def _verify_committed_authorization(self, reaper, uid, stage, transaction_id, snapshot, revision):
        """Recheck the signed committed revision while the fence is held."""
        with child_directory(reaper._comm_fd, self.get_matrix_universal_id()) as matrix_fd:
            state, _ = read_reap_authorization(matrix_fd, public_key=self.matrix_pub,
                universe=self.command_line_args["universe"], boot_id=self.path_resolution["reboot_uuid"],
                generation=os.environ.get("MATRIX_LIFECYCLE_GENERATION"))
        target = state["targets"].get(uid)
        operation = target.get("op") if isinstance(target, dict) else None
        valid_op = (operation in ("shutdown_restart", "shutdown_delete") if stage == "shutdown_probe"
                    else operation == ("shutdown_restart" if stage.startswith("restart_") else "shutdown_delete"))
        if (state["revision"] != revision or not isinstance(target, dict) or target.get("locked") is not True
                or not valid_op or target.get("transaction_id") != transaction_id or target.get("stage") != stage
                or (stage != "shutdown_probe" and target.get("target_snapshot") != snapshot)):
            raise ValueError("Matrix transaction changed after authorization")

    @contextmanager
    def _fenced_reaper(self):
        reaper = Reaper(self.path_resolution["pod_path"], self.path_resolution["comm_path"],
                        lifecycle_base=self.path_resolution["install_path"],
                        lifecycle_universe=self.command_line_args["universe"],
                        lifecycle_generation=os.environ.get("MATRIX_LIFECYCLE_GENERATION"))
        with reaper.lifecycle_guard():
            yield reaper

    @staticmethod
    def _validate_target_snapshot(stage, snapshot):
        if stage == "shutdown_probe":
            if snapshot is not None:
                raise ValueError("Unexpected probe target snapshot")
            return None
        if not isinstance(snapshot, list) or len(snapshot) > 1024:
            raise ValueError("Reaper transaction has no valid probed target identity")
        names = set()
        for item in snapshot:
            if (not isinstance(item, dict) or set(item) != {"pod", "pid", "process_started_at", "record_sha256"}
                    or type(item["pid"]) is not int or item["pid"] <= 0
                    or type(item["process_started_at"]) not in (int, float)
                    or not isinstance(item["record_sha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", item["record_sha256"])):
                raise ValueError("Invalid probed target identity")
            validate_agent_ids((item["pod"],))
            if item["pod"] in names:
                raise ValueError("Duplicate probed target pod")
            names.add(item["pod"])
        return snapshot

    def _visible_target_jobs(self, uid):
        """Do not infer absence when procfs hides a possible universe job."""
        try:
            lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
            proc_mount = next(line.split() for line in lines if len(line.split()) > 9 and line.split()[4] == "/proc" and "-" in line.split() and line.split()[line.split().index("-") + 1] == "proc")
            separator = proc_mount.index("-")
            options = (proc_mount[5] + "," + proc_mount[separator + 3]).split(",")
            if any(value.startswith("hidepid=") and value != "hidepid=0" for value in options):
                raise RuntimeError("Restricted procfs hides processes")
        except (OSError, StopIteration, IndexError) as exc:
            raise RuntimeError("Cannot verify procfs visibility") from exc
        label = f"{self.command_line_args['universe']}:{uid}"
        result = set()
        for proc in psutil.process_iter(["pid", "cmdline", "status", "ppid"]):
            try:
                info = proc.info
                if info.get("status") == psutil.STATUS_ZOMBIE:
                    continue
                cmd = info.get("cmdline")
                if cmd is None:
                    raise RuntimeError("Cannot inspect all processes")
                if not cmd:
                    if info.get("pid") == 2 or info.get("ppid") == 2:
                        continue
                    raise RuntimeError("Cannot establish process identity")
                if _matches_job(cmd, label):
                    result.add(info["pid"])
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied as exc:
                raise RuntimeError("Cannot inspect all processes") from exc
        return result

    @contextmanager
    def _target_snapshot(self, reaper, uid):
        """Pin every recorded target and reject unrecorded live processes."""
        records, refs = [], []
        try:
            for pod_name in os.listdir(reaper._pod_fd):
                record = reaper._read_boot_record(pod_name)
                record_uid = record.get("universal_id")
                validate_agent_ids((record_uid,))
                if record_uid != uid:
                    continue
                pid = record.get("pid")
                cmd = record.get("cmd")
                if not _matches_job(cmd, f"{self.command_line_args['universe']}:{uid}"):
                    raise ValueError("Target boot record has an invalid job identity")
                digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                records.append({"pod": pod_name, "pid": pid,
                                "process_started_at": record.get("process_started_at"), "record_sha256": digest})
                try:
                    ref = PinnedProcess(pid, record.get("process_started_at"), expected_cmd=cmd)
                except (psutil.NoSuchProcess, ProcessLookupError):
                    continue
                refs.append(ref)
            visible = self._visible_target_jobs(uid)
            live = [ref for ref in refs if ref.is_alive()]
            if visible != {ref.pid for ref in live}:
                raise RuntimeError("Unrecorded or uninspectable target process")
            yield records, live
        finally:
            for ref in refs:
                ref.close()

    def _drop_die(self, reaper, uid):
        with child_directory(reaper._comm_fd, uid, create=True) as agent_fd:
            with child_directory(agent_fd, "incoming", create=True) as incoming_fd:
                write_file_at(incoming_fd, "die", json.dumps("terminate").encode())

    @staticmethod
    def _terminate(refs):
        for ref in refs:
            ref.send_signal(signal.SIGTERM)
        if refs:
            time.sleep(2)
        for ref in refs:
            if ref.is_alive():
                ref.kill()
        if refs:
            time.sleep(1)
        if any(ref.is_alive() for ref in refs):
            raise RuntimeError("Target process remains alive after escalation")

    def _clean_target(self, reaper, uid, records, *, remove_comm):
        """Preflight all target paths, then delete only anchored directories."""
        for entry in records:
            pod_name = entry["pod"]
            with child_directory(reaper._pod_fd, pod_name) as pod_fd:
                _tree_preflight(pod_fd)
        try:
            with child_directory(reaper._comm_fd, uid) as comm_fd:
                if remove_comm:
                    _tree_preflight(comm_fd)
                else:
                    try:
                        with child_directory(comm_fd, "incoming") as incoming_fd:
                            self._regular_marker_exists(incoming_fd, "die")
                    except FileNotFoundError:
                        pass
        except FileNotFoundError:
            pass
        # Recheck process visibility immediately before the destructive step;
        # the exclusive lifecycle guard prevents cooperating spawns meanwhile.
        with self._target_snapshot(reaper, uid) as (current, live):
            if live:
                raise RuntimeError("Target is still running; cleanup refused")
            if {item["pod"]: item for item in current} != {item["pod"]: item for item in records}:
                raise RuntimeError("Target pod records changed before cleanup")
        for entry in records:
            pod_name = entry["pod"]
            with child_directory(reaper._pod_fd, pod_name) as pod_fd:
                _remove_contents(pod_fd)
            os.rmdir(pod_name, dir_fd=reaper._pod_fd)
        try:
            comm_context = child_directory(reaper._comm_fd, uid)
            comm_fd = comm_context.__enter__()
        except FileNotFoundError:
            return
        try:
            if remove_comm:
                _remove_contents(comm_fd)
            else:
                try:
                    with child_directory(comm_fd, "incoming") as incoming_fd:
                        if self._regular_marker_exists(incoming_fd, "die"):
                            identity = self._regular_entry_identity(incoming_fd, "die")
                            if not self._unlink_received_entry(incoming_fd, "die", identity):
                                raise RuntimeError("Die marker changed during cleanup")
                except FileNotFoundError:
                    pass
        finally:
            comm_context.__exit__(None, None, None)
        if remove_comm:
            os.rmdir(uid, dir_fd=reaper._comm_fd)

    def _run_stage(self, reaper, uid, stage, expected_snapshot):
        with self._target_snapshot(reaper, uid) as (records, live):
            if stage == "shutdown_probe":
                return ("alive" if live else "dead" if records else "already_dead"), {"target_snapshot": records}
            expected = {entry["pod"]: entry for entry in expected_snapshot}
            if any(entry["pod"] not in expected or entry != expected[entry["pod"]] for entry in records):
                raise RuntimeError("Target pod or process changed since shutdown probe")
            if stage in ("restart_start", "delete_start"):
                if live:
                    self._drop_die(reaper, uid)
                    return "alive", {}
                return "dead", {}
            if stage in ("restart_wait", "restart_escalate", "delete_escalate"):
                self._terminate(live)
                with self._target_snapshot(reaper, uid) as (_, remaining):
                    if remaining:
                        raise RuntimeError("Target restarted during escalation")
                if stage == "restart_wait":
                    self._clean_target(reaper, uid, records, remove_comm=False)
                    return "pod_cleared", {}
                return "terminated", {}
            if stage in ("restart_cleanup", "delete_cleanup"):
                if live:
                    raise RuntimeError("Target is still running; cleanup refused")
                self._clean_target(reaper, uid, records, remove_comm=(stage == "delete_cleanup"))
                return "cleaned", {}
            raise ValueError(f"Unknown Reaper stage: {stage}")

    def _report_to_matrix(self, uid, stage, success, error=None, extra=None, *, transaction_id):
        try:
            payload = {"handler": "cmd_reap_status", "content": {"universal_id": uid, "stage": stage, "transaction_id": transaction_id,
                       "result": {"success": success, "error": error, **(extra or {})}},
                       "timestamp": time.time(), "origin": self.command_line_args.get("universal_id", "reaper")}
            packet = self.get_delivery_packet("standard.command.packet")
            packet.set_data(payload)
            if not self.pass_packet(packet, self.get_matrix_universal_id()):
                self.log(f"[REAPER][ERROR] Could not report {stage} for {uid}.")
        except Exception as exc:
            self.log("[REAPER][ERROR] Failed to report status.", error=exc)


if __name__ == "__main__":
    agent = Agent()
    agent.boot()
