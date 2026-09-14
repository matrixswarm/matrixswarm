"""Durable RsyncBoy scheduling and thread completion regressions."""

from pathlib import Path
import os
import sys
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("SITE_ROOT", str(ROOT / "matrixos"))
os.environ.setdefault(
    "AGENT_PATH", str(ROOT / "matrixos" / "agents" / "python_core" / "rsync_boy")
)
sys.path.insert(0, str(ROOT / "matrixos" / "agents" / "python_core"))
sys.path.insert(0, str(ROOT / "matrixos"))

from core.python_core.class_lib.processes.thread_launcher import ThreadLauncher

# Loading BootAgent pulls in every production transport dependency. This unit
# suite exercises only RsyncBoy's scheduler methods, so isolate that import from
# optional runtime packages that are intentionally absent in lean test envs.
boot_module_name = "core.python_core.boot_agent"
identity_module_name = (
    "core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity"
)
saved_boot_module = sys.modules.get(boot_module_name)
saved_identity_module = sys.modules.get(identity_module_name)
boot_module = types.ModuleType(boot_module_name)
identity_module = types.ModuleType(identity_module_name)
boot_module.BootAgent = type("BootAgent", (), {})
identity_module.IdentityObject = type("IdentityObject", (), {})
sys.modules[boot_module_name] = boot_module
sys.modules[identity_module_name] = identity_module
try:
    from rsync_boy.rsync_boy import Agent
finally:
    sys.modules.pop("rsync_boy.rsync_boy", None)
    if saved_boot_module is None:
        sys.modules.pop(boot_module_name, None)
    else:
        sys.modules[boot_module_name] = saved_boot_module
    if saved_identity_module is None:
        sys.modules.pop(identity_module_name, None)
    else:
        sys.modules[identity_module_name] = saved_identity_module


def scheduler(entries=None):
    agent = object.__new__(Agent)
    agent.retry_interval = 900
    agent.launch_stagger_sec = 5
    agent.running = True
    agent._scheduler_lock = threading.RLock()
    agent._scheduler_state = {"version": 1, "jobs": entries or {}}
    agent._last_attempt = {}
    agent._running = {}
    agent.save_encrypted_state = Mock()
    agent.log = Mock()
    return agent


def job(path="/sites/"):
    return {
        "id": "sites",
        "enabled": True,
        "factory": "filesystem.rsync_snapshot.RsyncSnapshotJob",
        "schedule": {"interval_sec": 86400, "run_on_boot": True},
        "config": {"source_path": path},
    }


class RsyncBoySchedulerTests(unittest.TestCase):
    def test_success_survives_restart_but_changed_job_runs(self):
        original = job()
        completed = {
            "sites": {
                "last_success": 1000.0,
                "definition_hash": Agent._job_definition_hash(original),
            }
        }
        restarted = scheduler(completed)

        self.assertFalse(restarted._job_due(original, 1001.0))
        self.assertTrue(restarted._job_due(job("/static_content/"), 1001.0))

    def test_only_success_is_persisted(self):
        agent = scheduler()
        definition_hash = Agent._job_definition_hash(job())
        agent._running["sites"] = "thread-a"

        agent._job_completed(
            "sites", definition_hash,
            {"result": "error", "finished_at": 1000.0},
        )
        self.assertNotIn("sites", agent._scheduler_state["jobs"])
        agent.save_encrypted_state.assert_not_called()

        agent._running["sites"] = "thread-b"
        agent._job_completed(
            "sites", definition_hash,
            {"result": "ok", "finished_at": 1001.0},
        )
        self.assertEqual(
            agent._scheduler_state["jobs"]["sites"]["last_success"],
            1001.0,
        )
        agent.save_encrypted_state.assert_called_once()

    def test_running_and_failed_jobs_do_not_relaunch_immediately(self):
        agent = scheduler()
        candidate = job()
        agent._running["sites"] = "thread-a"
        self.assertFalse(agent._job_due(candidate, 1000.0))

        agent._running.clear()
        agent._last_attempt["sites"] = 1000.0
        self.assertFalse(agent._job_due(candidate, 1001.0))
        self.assertTrue(agent._job_due(candidate, 1900.0))

    def test_due_jobs_are_staggered_without_serializing_transfers(self):
        agent = scheduler()
        agent.jobs = []
        for job_id in ("sites", "etc", "cron"):
            candidate = job(f"/{job_id}/")
            candidate["id"] = job_id
            agent.jobs.append(candidate)
        agent._job_due = Mock(return_value=True)
        agent._launch_job = Mock()
        sleeps = []

        with patch.dict(
            Agent._launch_due_jobs.__globals__,
            {"interruptible_sleep": lambda _agent, seconds: sleeps.append(seconds)},
        ):
            agent._launch_due_jobs(1000.0)

        self.assertEqual(
            [call.args[0]["id"] for call in agent._launch_job.call_args_list],
            ["sites", "etc", "cron"],
        )
        self.assertEqual(sleeps, [5, 5])

    def test_launch_stagger_is_bounded(self):
        self.assertEqual(Agent._normalize_launch_stagger(0), 0)
        self.assertEqual(Agent._normalize_launch_stagger("5"), 5)
        for invalid in (-1, 61, "nan"):
            with self.assertRaises(ValueError):
                Agent._normalize_launch_stagger(invalid)


class ThreadLauncherCompletionTests(unittest.TestCase):
    def test_callback_receives_safe_success_record_before_cleanup(self):
        completed = []
        done = threading.Event()

        class Worker:
            def __init__(self, log, shared):
                self.shared = shared

            def run(self):
                self.shared["result"] = "ok"

        launcher = ThreadLauncher(lambda *args, **kwargs: None)
        launcher._load_class = lambda _path: Worker

        thread_id = launcher.launch(
            "fixture.Worker",
            context={"password": "never-copy-this"},
            on_complete=lambda record: (completed.append(record), done.set()),
        )
        self.assertTrue(done.wait(2))

        deadline = time.monotonic() + 2
        while thread_id in launcher._threads and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(completed[0]["result"], "ok")
        self.assertNotIn("context", completed[0])
        self.assertNotIn("password", repr(completed[0]))
        self.assertNotIn(thread_id, launcher._threads)


if __name__ == "__main__":
    unittest.main()
