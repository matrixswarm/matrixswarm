# Authored by Daniel F MacDonald and ChatGPT aka The Generals
import sys, os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))


import hashlib
import json
import math
import re
import threading
import time
from core.python_core.boot_agent import BootAgent
from core.python_core.mixin.encrypted_state import EncryptedStateMixin
from core.python_core.utils.swarm_sleep import interruptible_sleep
from core.python_core.class_lib.processes.thread_launcher import ThreadLauncher
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from rsync_boy.job_config import normalize_jobs, normalize_poll_interval


class Agent(EncryptedStateMixin, BootAgent):
    """
    rsync_boy — Job Dispatcher
    -------------------------
    • Reads declarative job definitions from config
    • Decides when jobs should fire
    • Launches ephemeral factory threads
    • Never performs work itself
    """

    def __init__(self):
        super().__init__()
        self.AGENT_VERSION = "2.3.0"

        cfg = self.tree_node.get("config", {}) or {}
        self._rpc_role = cfg.get("rpc_router_role", "hive.rpc")
        self.init_encrypted_state(namespace="rsync_boy_scheduler")
        self._scheduler_lock = threading.RLock()
        job_config = self._load_job_config(cfg)
        self._job_config_revision = job_config["revision"]
        self.poll_interval = job_config["poll_interval"]
        self.retry_interval = max(
            self.poll_interval,
            int(job_config["retry_interval_sec"]),
        )
        self.launch_stagger_sec = self._normalize_launch_stagger(
            job_config["launch_stagger_sec"]
        )
        self.jobs = job_config["jobs"]
        self._scheduler_state = self._load_scheduler_state()
        self._last_attempt = {}
        self._running = {}
        self.thread_launcher = ThreadLauncher(self)

        self._emit_beacon = self.check_for_thread_poke(
            "worker",
            timeout=self.poll_interval * 2,
            emit_to_file_interval=10
        )

        completed = len(self._scheduler_state["jobs"])
        self.log(
            f"[RSYNC_BOY] Loaded {len(self.jobs)} jobs; "
            f"restored {completed} successful schedule entries; "
            f"launch stagger {self.launch_stagger_sec:g}s"
        )

    # --------------------------------------------------
    def _load_job_config(self, initial: dict) -> dict:
        saved = self.load_encrypted_state("job_config", default=None)
        if saved is None:
            source = {
                "version": 1,
                "revision": 0,
                "poll_interval": int(initial.get("poll_interval", 60)),
                "retry_interval_sec": int(initial.get("retry_interval_sec", 900)),
                "launch_stagger_sec": initial.get("launch_stagger_sec", 5),
                "jobs": initial.get("jobs", []),
            }
        else:
            source = saved
        if not isinstance(source, dict) or source.get("version") != 1:
            raise ValueError("invalid RsyncBoy job configuration version")
        revision = source.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("invalid RsyncBoy job configuration revision")
        poll_interval = normalize_poll_interval(source.get("poll_interval"))
        retry = source.get("retry_interval_sec", 900)
        if isinstance(retry, bool) or not isinstance(retry, int) or not 1 <= retry <= 86400:
            raise ValueError("retry_interval_sec must be between 1 and 86400")
        stagger = self._normalize_launch_stagger(source.get("launch_stagger_sec", 5))
        return {
            "version": 1,
            "revision": revision,
            "poll_interval": poll_interval,
            "retry_interval_sec": retry,
            "launch_stagger_sec": stagger,
            "jobs": normalize_jobs(source.get("jobs", [])),
        }

    # --------------------------------------------------
    @staticmethod
    def _normalize_launch_stagger(value) -> float:
        stagger = float(value)
        if not math.isfinite(stagger) or not 0 <= stagger <= 60:
            raise ValueError("launch_stagger_sec must be between 0 and 60")
        return stagger

    # --------------------------------------------------
    def _load_scheduler_state(self) -> dict:
        state = self.load_encrypted_state(
            "completed_jobs", default={"version": 1, "jobs": {}}
        )
        if not isinstance(state, dict) or state.get("version") != 1:
            raise ValueError("invalid RsyncBoy scheduler state version")
        entries = state.get("jobs")
        if not isinstance(entries, dict):
            raise ValueError("invalid RsyncBoy scheduler job ledger")

        validated = {}
        for job_id, entry in entries.items():
            if not isinstance(job_id, str) or not job_id or not isinstance(entry, dict):
                raise ValueError("invalid RsyncBoy scheduler job entry")
            last_success = entry.get("last_success")
            definition_hash = entry.get("definition_hash")
            if (
                isinstance(last_success, bool)
                or not isinstance(last_success, (int, float))
                or not math.isfinite(last_success)
                or last_success <= 0
                or not isinstance(definition_hash, str)
                or len(definition_hash) != 64
                or any(c not in "0123456789abcdef" for c in definition_hash)
            ):
                raise ValueError("invalid RsyncBoy scheduler completion record")
            validated[job_id] = {
                "last_success": float(last_success),
                "definition_hash": definition_hash,
            }
        return {"version": 1, "jobs": validated}

    # --------------------------------------------------
    @staticmethod
    def _job_definition_hash(job: dict) -> str:
        definition = {
            "factory": job.get("factory"),
            "config": job.get("config", {}),
        }
        encoded = json.dumps(
            definition,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    # --------------------------------------------------
    def _job_due(self, job, now: float) -> bool:
        job_id = job.get("id")
        sched = job.get("schedule", {}) or {}

        interval = int(sched.get("interval_sec", 0))
        run_on_boot = bool(sched.get("run_on_boot", False))

        definition_hash = self._job_definition_hash(job)
        with self._scheduler_lock:
            if job_id in self._running:
                return False
            entry = self._scheduler_state["jobs"].get(job_id)
            last_attempt = self._last_attempt.get(job_id)

        if entry and entry.get("definition_hash") == definition_hash:
            last_success = entry["last_success"]
        else:
            last_success = None

        if last_success is None:
            if last_attempt is not None and now - last_attempt < self.retry_interval:
                return False
            return run_on_boot or interval > 0

        if interval <= 0:
            return False

        if (now - last_success) < interval:
            return False

        if last_attempt is not None and last_attempt > last_success:
            return (now - last_attempt) >= self.retry_interval
        return True

    # --------------------------------------------------
    def _job_completed(self, job_id: str, definition_hash: str, completion: dict):
        result = completion.get("result")
        with self._scheduler_lock:
            self._running.pop(job_id, None)
            if result != "ok":
                self.log(
                    f"[RSYNC_BOY] Job '{job_id}' failed; completion was not "
                    f"recorded and retry is eligible in {self.retry_interval}s",
                    level="WARN",
                )
                return

            finished_at = completion.get("finished_at", time.time())
            if (
                isinstance(finished_at, bool)
                or not isinstance(finished_at, (int, float))
                or not math.isfinite(finished_at)
                or finished_at <= 0
            ):
                finished_at = time.time()

            previous = self._scheduler_state["jobs"].get(job_id)
            self._scheduler_state["jobs"][job_id] = {
                "last_success": float(finished_at),
                "definition_hash": definition_hash,
            }
            try:
                self.save_encrypted_state(
                    "completed_jobs", self._scheduler_state
                )
            except Exception:
                if previous is None:
                    self._scheduler_state["jobs"].pop(job_id, None)
                else:
                    self._scheduler_state["jobs"][job_id] = previous
                raise

        self.log(
            f"[RSYNC_BOY] Job '{job_id}' completed; encrypted schedule state saved"
        )

    # --------------------------------------------------
    def _jobs_snapshot(self) -> dict:
        with self._scheduler_lock:
            jobs = json.loads(json.dumps(self.jobs))
            runtime = {}
            for job in jobs:
                job_id = job["id"]
                completion = self._scheduler_state["jobs"].get(job_id, {})
                last_success = None
                if completion.get("definition_hash") == self._job_definition_hash(job):
                    last_success = completion.get("last_success")
                runtime[job_id] = {
                    "running": job_id in self._running,
                    "last_attempt": self._last_attempt.get(job_id),
                    "last_success": last_success,
                }
            return {
                "revision": self._job_config_revision,
                "poll_interval": self.poll_interval,
                "jobs": jobs,
                "runtime": runtime,
            }

    # --------------------------------------------------
    def _authorized(self, content, identity):
        return (
            isinstance(content, dict)
            and content.get("target_universal_id")
            == self.command_line_args.get("universal_id")
            and isinstance(identity, IdentityObject)
            and identity.has_verified_identity()
            and identity.get_sender_uid() == self.get_matrix_universal_id()
        )

    # --------------------------------------------------
    @staticmethod
    def _callback_fields(content):
        for key in ("session_id", "token", "request_id"):
            value = content.get(key)
            if not isinstance(value, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,128}", value
            ):
                raise ValueError(f"Invalid {key}")
        return content["session_id"], content["token"]

    # --------------------------------------------------
    def _reply(self, content, payload):
        session, token = self._callback_fields(content)
        return self.crypto_reply(
            response_handler="rsync_boy.jobs",
            payload=dict(
                payload,
                agent_uid=self.command_line_args["universal_id"],
                token=token,
                request_id=content["request_id"],
            ),
            session_id=session,
            token=token,
            rpc_role=self._rpc_role,
            quiet=True,
        )

    # --------------------------------------------------
    def cmd_retrieve_jobs(self, content, packet, identity=None):
        if not self._authorized(content, identity):
            return
        self._reply(content, dict(self._jobs_snapshot(), ok=True))

    # --------------------------------------------------
    def cmd_update_jobs(self, content, packet, identity=None):
        if not self._authorized(content, identity):
            return
        self._callback_fields(content)
        try:
            jobs = normalize_jobs(content.get("jobs"))
            poll_interval = normalize_poll_interval(content.get("poll_interval"))
            with self._scheduler_lock:
                revision = content.get("revision")
                if revision != self._job_config_revision:
                    raise ValueError(
                        "Job configuration changed on the server; reload before saving"
                    )
                document = {
                    "version": 1,
                    "revision": self._job_config_revision + 1,
                    "poll_interval": poll_interval,
                    "retry_interval_sec": self.retry_interval,
                    "launch_stagger_sec": self.launch_stagger_sec,
                    "jobs": jobs,
                }
                # Persist first. A storage failure must never alter the live schedule.
                self.save_encrypted_state("job_config", document)
                self.jobs = jobs
                self.poll_interval = poll_interval
                self.retry_interval = max(poll_interval, self.retry_interval)
                self._job_config_revision = document["revision"]
        except ValueError as exc:
            self._reply(content, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:
            self.log(
                f"[RSYNC_BOY] Cannot persist job configuration: {type(exc).__name__}",
                level="ERROR",
            )
            self._reply(
                content,
                {
                    "ok": False,
                    "error": "Could not save encrypted state; changes were not accepted",
                },
            )
            return
        self.log(
            f"[RSYNC_BOY] Live job configuration saved at revision "
            f"{self._job_config_revision}"
        )
        self._reply(content, dict(self._jobs_snapshot(), ok=True))

    # --------------------------------------------------
    def cmd_execute_job(self, content, packet, identity=None):
        if not self._authorized(content, identity):
            return
        self._callback_fields(content)
        job_id = content.get("job_id")
        try:
            if not isinstance(job_id, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", job_id
            ):
                raise ValueError("Invalid job id")
            with self._scheduler_lock:
                job = next((item for item in self.jobs if item["id"] == job_id), None)
                already_running = job_id in self._running
            if job is None:
                raise ValueError("Job no longer exists on the server; reload the panel")
            if already_running:
                raise ValueError("Job is already running")
            self._launch_job(job)
        except ValueError as exc:
            self._reply(content, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:
            self.log(
                f"[RSYNC_BOY] Manual launch failed for '{job_id}': {type(exc).__name__}",
                level="ERROR",
            )
            self._reply(content, {"ok": False, "error": "Job could not be started"})
            return
        self._reply(
            content,
            dict(self._jobs_snapshot(), ok=True, message=f"Started job '{job_id}'"),
        )

    # --------------------------------------------------
    def _launch_job(self, job):
        job_id = job["id"]
        factory = job.get("factory")

        if not factory:
            self.log(
                f"[RSYNC_BOY][WARN] Job {job_id} missing factory",
                level="WARN",
            )
            return None

        definition_hash = self._job_definition_hash(job)
        with self._scheduler_lock:
            if job_id in self._running:
                return None
            self._running[job_id] = "launching"
            self._last_attempt[job_id] = time.time()

        try:
            # Start with the job-local config, then inject resolved secrets only
            # into the ephemeral thread context. They never enter schedule state.
            cfg = job.get("config", {}).copy()
            top_cfg = self.tree_node.get("config", {})
            if "ssh" in top_cfg:
                cfg["ssh"] = top_cfg["ssh"]
                self.log(
                    "[RSYNC_BOY][_LAUNCH_JOB] Injected SSH creds from "
                    "top-level config."
                )
            if "mysql" in top_cfg:
                cfg["mysql"] = top_cfg["mysql"]
                self.log(
                    "[RSYNC_BOY][_LAUNCH_JOB] Injected MySQL creds from "
                    "top-level config."
                )

            context = {"job_id": job_id, "config": cfg}
            self.log(f"[RSYNC_BOY] Launching job '{job_id}' → {factory}")
            thread_id = self.thread_launcher.launch(
                class_path=f"rsync_boy.factory.{factory}",
                context=context,
                persist=False,
                on_complete=lambda completion: self._job_completed(
                    job_id, definition_hash, completion
                ),
            )
        except Exception:
            with self._scheduler_lock:
                self._running.pop(job_id, None)
            raise

        with self._scheduler_lock:
            if self._running.get(job_id) == "launching":
                self._running[job_id] = thread_id
        return thread_id

    # --------------------------------------------------
    def _launch_due_jobs(self, now: float):
        with self._scheduler_lock:
            configured_jobs = list(self.jobs)
        due_jobs = [
            job for job in configured_jobs
            if job.get("enabled", False) and self._job_due(job, now)
        ]
        if len(due_jobs) > 1 and self.launch_stagger_sec:
            self.log(
                f"[RSYNC_BOY] Staggering {len(due_jobs)} due jobs by "
                f"{self.launch_stagger_sec:g}s between launches"
            )

        for index, job in enumerate(due_jobs):
            try:
                self._launch_job(job)
            except Exception as exc:
                self.log(
                    error=exc,
                    block="job_launch",
                    level="ERROR",
                )

            if index < len(due_jobs) - 1 and self.launch_stagger_sec:
                interruptible_sleep(self, self.launch_stagger_sec)
                if not self.running:
                    break

    # --------------------------------------------------
    def worker(self, config=None, identity: IdentityObject = None):
        try:
            self._emit_beacon()
            now = time.time()

            # The encrypted server-side job document is authoritative. This
            # legacy update path remains for non-job timing knobs only.
            if isinstance(config, dict) and bool(config.get("push_live_config", 0)):
                self.retry_interval = max(
                    self.poll_interval,
                    int(config.get("retry_interval_sec", self.retry_interval)),
                )
                self.launch_stagger_sec = self._normalize_launch_stagger(
                    config.get("launch_stagger_sec", self.launch_stagger_sec)
                )
                self.log("[RSYNC_BOY] Live runtime timing updated")

            self._launch_due_jobs(now)

        except Exception as e:
            self.log("[RSYNC_BOY][ERROR]", error=e)

        interruptible_sleep(self, self.poll_interval)


if __name__ == "__main__":
    agent = Agent()
    agent.boot()
