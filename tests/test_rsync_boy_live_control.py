"""Security and contract regressions for live RsyncBoy administration."""

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import threading
import time
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = ROOT / "matrixos/agents/python_core/rsync_boy"

import sys
sys.path.insert(0, str(AGENT_PATH))
from job_config import (  # noqa: E402
    FILESYSTEM_FACTORY,
    MYSQL_FACTORY,
    normalize_jobs,
)


class Identity:
    def __init__(self, verified=True, sender="matrix-one"):
        self.verified = verified
        self.sender = sender

    def has_verified_identity(self):
        return self.verified

    def get_sender_uid(self):
        return self.sender


def sample_job(job_id="sites"):
    return {
        "id": job_id,
        "enabled": True,
        "factory": FILESYSTEM_FACTORY,
        "schedule": {"interval_sec": 86400, "run_on_boot": True},
        "config": {
            "source_via_ssh": True,
            "source_path": "/sites",
            "remote_path": "/backup/snapshots/sites",
            "snapshot_prefix": "sites",
            "exclude": ["*/data/cache/***"],
            "link_dest": True,
            "preserve_hard_links": True,
            "preserve_acls": True,
            "preserve_xattrs": True,
            "remote_prune": {"keep_days": 14},
        },
    }


def load_agent_class():
    path = AGENT_PATH / "rsync_boy.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Agent")
    cls.bases = []
    namespace = {
        "IdentityObject": Identity,
        "normalize_jobs": normalize_jobs,
        "normalize_poll_interval": lambda value: value if type(value) is int and 1 <= value <= 86400 else (_ for _ in ()).throw(ValueError("invalid poll")),
        "re": re,
        "json": json,
        "hashlib": hashlib,
        "time": time,
        "threading": threading,
    }
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), "exec"),
        namespace,
    )
    return namespace["Agent"]


def live_agent():
    cls = load_agent_class()
    agent = cls.__new__(cls)
    agent.command_line_args = {"universal_id": "rsync-one"}
    agent.get_matrix_universal_id = lambda: "matrix-one"
    agent._rpc_role = "hive.rpc"
    agent._scheduler_lock = threading.RLock()
    agent.jobs = normalize_jobs([sample_job()])
    agent.poll_interval = 60
    agent.retry_interval = 900
    agent.launch_stagger_sec = 5
    agent._job_config_revision = 2
    agent._scheduler_state = {"version": 1, "jobs": {}}
    agent._last_attempt = {}
    agent._running = {}
    agent._ssh_profiles = {}
    agent.tree_node = {"config": {}}
    agent.save_encrypted_state = Mock()
    agent.log = Mock()
    agent.crypto_reply = Mock()
    agent.thread_launcher = Mock()
    agent.thread_launcher.launch.return_value = "thread-one"
    return agent


def request(**extra):
    value = {
        "target_universal_id": "rsync-one",
        "session_id": "session-one",
        "token": "token-one",
        "request_id": "request-one",
    }
    value.update(extra)
    return value


class JobSchemaTests(unittest.TestCase):
    def test_normalizes_supported_job_and_rejects_credentials(self):
        normalized = normalize_jobs([sample_job()])
        self.assertEqual(normalized[0]["factory"], FILESYSTEM_FACTORY)
        poisoned = sample_job()
        poisoned["config"]["ssh"] = {"password": "secret"}
        with self.assertRaisesRegex(ValueError, "credentials"):
            normalize_jobs([poisoned])

    def test_rejects_duplicate_ids_and_unknown_factories(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            normalize_jobs([sample_job(), sample_job()])
        unknown = sample_job()
        unknown["factory"] = "subprocess.anything.RootJob"
        with self.assertRaisesRegex(ValueError, "unsupported"):
            normalize_jobs([unknown])

    def test_mysql_job_is_supported(self):
        mysql = {
            "id": "mysql-full",
            "enabled": True,
            "factory": MYSQL_FACTORY,
            "schedule": {"interval_sec": 86400, "run_on_boot": False},
            "config": {
                "remote_path": "/srv/backups/mysql",
                "local_tmp": "/tmp/mysql_dumps",
                "dump_flags": "--single-transaction",
                "mysql_via_ssh": True,
                "compress": True,
                "filename_prefix": "dragoart",
                "remote_prune": {"keep_days": 14},
            },
        }
        self.assertEqual(normalize_jobs([mysql])[0]["id"], "mysql-full")

    def test_profile_reference_is_preserved_without_credentials(self):
        candidate = sample_job()
        candidate["ssh_profile"] = "cdn-assets-01"
        normalized = normalize_jobs([candidate])[0]
        self.assertEqual(normalized["ssh_profile"], "cdn-assets-01")
        self.assertNotIn("ssh", normalized["config"])
        candidate["ssh_profile"] = "../unsafe"
        with self.assertRaisesRegex(ValueError, "unsafe"):
            normalize_jobs([candidate])

    def test_profile_change_changes_schedule_definition(self):
        cls = load_agent_class()
        primary = sample_job()
        cdn = sample_job()
        cdn["ssh_profile"] = "cdn-assets-01"
        self.assertNotEqual(
            cls._job_definition_hash(primary),
            cls._job_definition_hash(cdn),
        )


class AgentProtocolTests(unittest.TestCase):
    def setUp(self):
        self.agent = live_agent()
        self.identity = Identity()

    def _reply_payload(self):
        return self.agent.crypto_reply.call_args.kwargs["payload"]

    def test_exact_target_and_verified_matrix_identity_are_required(self):
        for identity in (None, Identity(False), Identity(True, "someone-else")):
            self.agent.cmd_retrieve_jobs(request(), None, identity)
        self.agent.cmd_retrieve_jobs(
            request(target_universal_id="rsync-two"), None, self.identity
        )
        self.agent.crypto_reply.assert_not_called()
        self.agent.cmd_retrieve_jobs(request(), None, self.identity)
        self.assertTrue(self._reply_payload()["ok"])
        self.assertEqual(self._reply_payload()["agent_uid"], "rsync-one")
        self.assertTrue(self.agent.crypto_reply.call_args.kwargs["quiet"])

    def test_update_is_revision_checked_and_disk_failure_is_atomic(self):
        updated = sample_job("static")
        self.agent.cmd_update_jobs(
            request(revision=2, poll_interval=30, jobs=[updated]),
            None,
            self.identity,
        )
        self.assertTrue(self._reply_payload()["ok"])
        self.assertEqual(self.agent._job_config_revision, 3)
        self.assertEqual(self.agent.jobs[0]["id"], "static")
        saved = self.agent.save_encrypted_state.call_args.args[1]
        self.assertEqual(saved["revision"], 3)
        self.assertNotIn("ssh", saved["jobs"][0]["config"])
        self.assertNotIn("mysql", saved["jobs"][0]["config"])

        before = deepcopy(self.agent.jobs)
        self.agent.save_encrypted_state.side_effect = OSError("disk full")
        self.agent.cmd_update_jobs(
            request(revision=3, poll_interval=40, jobs=[sample_job("cron")]),
            None,
            self.identity,
        )
        self.assertFalse(self._reply_payload()["ok"])
        self.assertEqual(self.agent.jobs, before)
        self.assertEqual(self.agent._job_config_revision, 3)

        self.agent.save_encrypted_state.side_effect = None
        self.agent.cmd_update_jobs(
            request(revision=2, poll_interval=40, jobs=[sample_job("cron")]),
            None,
            self.identity,
        )
        self.assertFalse(self._reply_payload()["ok"])
        self.assertIn("reload", self._reply_payload()["error"])

    def test_execute_now_launches_only_current_server_job(self):
        self.agent.cmd_execute_job(request(job_id="sites"), None, self.identity)
        self.assertTrue(self._reply_payload()["ok"])
        self.assertTrue(self._reply_payload()["runtime"]["sites"]["running"])
        launch = self.agent.thread_launcher.launch.call_args
        self.assertEqual(launch.kwargs["context"]["job_id"], "sites")

        self.agent.cmd_execute_job(request(job_id="deleted"), None, self.identity)
        self.assertFalse(self._reply_payload()["ok"])
        self.assertIn("no longer exists", self._reply_payload()["error"])

    def test_selected_profile_is_injected_only_into_ephemeral_context(self):
        self.agent._ssh_profiles = {
            "cdn-assets-01": {
                "label": "CDN assets",
                "host": "push.example.test",
                "username": "backup",
                "password": "runtime-only-secret",
            }
        }
        selected = sample_job()
        selected["ssh_profile"] = "cdn-assets-01"
        self.agent.jobs = normalize_jobs([selected])

        self.agent.cmd_execute_job(request(job_id="sites"), None, self.identity)

        self.assertTrue(self._reply_payload()["ok"])
        context = self.agent.thread_launcher.launch.call_args.kwargs["context"]
        self.assertEqual(context["config"]["ssh"]["host"], "push.example.test")
        self.assertNotIn("runtime-only-secret", repr(self.agent.jobs))
        self.assertNotIn("password", repr(self._reply_payload()["ssh_profiles"]))
        self.assertNotIn("private_key", repr(self._reply_payload()["ssh_profiles"]))

    def test_missing_selected_profile_fails_closed(self):
        selected = sample_job()
        selected["ssh_profile"] = "not-in-this-deployment"
        self.agent.jobs = normalize_jobs([selected])

        self.agent.cmd_execute_job(request(job_id="sites"), None, self.identity)

        self.assertFalse(self._reply_payload()["ok"])
        self.agent.thread_launcher.launch.assert_not_called()


class PanelContractTests(unittest.TestCase):
    def test_panel_and_meta_expose_live_crud_services(self):
        panel_path = ROOT / "phoenix/matrix_gui/core/panel/custom_panels/rsync_boy/rsync_boy.py"
        source = panel_path.read_text(encoding="utf-8")
        ast.parse(source)
        for text in (
            "class RsyncBoy(PhoenixPanelInterface)",
            "JobEditorDialog",
            "New Job",
            "Execute Now",
            "hive.rsync_boy.",
            "inbound.verified.rsync_boy.jobs",
        ):
            self.assertIn(text, source)
        meta = json.loads((ROOT / "phoenix/agents_meta/rsync_boy.json").read_text())
        roles = meta["config"]["service-manager"][0]["role"]
        self.assertEqual(
            roles,
            [
                "hive.rsync_boy.get_jobs@cmd_retrieve_jobs",
                "hive.rsync_boy.update_jobs@cmd_update_jobs",
                "hive.rsync_boy.execute_job@cmd_execute_job",
            ],
        )

    def test_matrix_routes_rsync_panel_request_only_to_exact_target(self):
        path = ROOT / "matrixos/agents/python_core/matrix/matrix.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        method = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_cmd_service_request"
        )
        namespace = {"time": time, "IdentityObject": Identity}
        exec(
            compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(path), "exec"),
            namespace,
        )

        class PacketStub:
            def set_data(self, data):
                self.data = data

        matrix = Mock()
        matrix.command_line_args = {"universal_id": "matrix-one"}
        endpoints = []
        for uid in ("rsync-one", "rsync-two"):
            endpoint = Mock()
            endpoint.get_universal_id.return_value = uid
            endpoint.get_handler.return_value = "cmd_update_jobs"
            endpoints.append(endpoint)
        matrix.get_nodes_by_role.return_value = endpoints
        matrix.get_delivery_packet.side_effect = lambda _name: PacketStub()
        payload = {
            "target_universal_id": "rsync-two",
            "source_path": "/private/server/path",
        }
        namespace["_cmd_service_request"](
            matrix,
            {"service": "hive.rsync_boy.update_jobs", "payload": payload},
            None,
        )
        matrix.pass_packet.assert_called_once()
        self.assertEqual(matrix.pass_packet.call_args.args[1], "rsync-two")
        self.assertNotIn("/private/server/path", str(matrix.log.call_args_list))


if __name__ == "__main__":
    unittest.main()
