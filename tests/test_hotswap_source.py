"""Boot-scoped hotswap must stage safely and confirm an actual new process."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import time
import subprocess
import textwrap
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
spec = importlib.util.spec_from_file_location("matrix_hotswap_test", ROOT / "matrixos/agents/python_core/matrix/matrix.py")
module = importlib.util.module_from_spec(spec)
with patch.dict(os.environ, {"SITE_ROOT": str(ROOT / "matrixos"), "AGENT_PATH": str(ROOT / "matrixos/agents/python_core")}):
    spec.loader.exec_module(module)


class HotswapTests(unittest.TestCase):
    def setUp(self):
        self.agent = module.Agent.__new__(module.Agent)
        # These unit tests exercise handler semantics in isolation. The
        # lifecycle guard itself is covered by the integration test suite.
        for name in ("_cmd_hotswap_agent", "_cmd_restart_subtree", "_handle_replace_agent",
                     "_cmd_update_agent", "_handle_inject_agents"):
            method = getattr(module.Agent, name)
            setattr(self.agent, name, types.MethodType(method.__wrapped__, self.agent))
        self.agent.command_line_args = {"universal_id": "matrix", "universe": "test"}
        self.agent.meta = {}
        self.agent.tree_node = {}
        self.agent.running = True
        self.agent._hotswap_lock = threading.Lock()
        self.agent._hotswap_pending = set()
        self.agent._hotswap_transfers = {}
        self.agent._hotswap_closed = {}
        self.agent._hotswap_challenges = {}
        self.agent.log = Mock()
        self.agent.crypto_reply = Mock(return_value=True)
        self.node = {"universal_id": "target", "name": "worker", "src_embed": "old", "hash_bang": "oldhash"}
        self.tree = Mock()
        self.tree.get_node.side_effect = lambda uid: self.node if uid == "target" else None
        self.tree.get_subtree_nodes.return_value = []
        self.agent.get_agent_tree_master = Mock(return_value=self.tree)
        self.agent.save_agent_tree_master = Mock(return_value=True)
        self.agent.commit_reap_mutation = Mock()
        self.agent.defer_reap_side_effect = lambda fn: fn()
        self.agent.defer_reap_abort = lambda fn: None
        self.agent._hotswap_processes = Mock(return_value={(1, 1.0)})
        self.agent._cmd_restart_subtree = Mock()
        source = b"print('new source')\n"
        digest = hashlib.sha256(source).hexdigest()
        self.content = {"target_universal_id": "target", "session_id": "session", "token": "a" * 32,
                        "size": len(source), "count": 1, "sha256": digest,
                        "source_payload": {"payload": base64.b64encode(source).decode(), "sha256": digest}}
        self.agent._cmd_hotswap_challenge(self.content, {}, None)
        self.content["challenge"] = self.agent.crypto_reply.call_args.kwargs["payload"]["challenge"]
        self.agent.crypto_reply.reset_mock()

    def test_valid_source_is_saved_in_tree_then_restart_requested(self):
        with patch.object(module.threading, "Thread") as worker:
            self.agent._cmd_hotswap_agent(self.content, {}, None)
        self.assertEqual(self.node["src_embed"], self.content["source_payload"]["payload"])
        self.assertEqual(self.node["hash_bang"], self.content["source_payload"]["sha256"])
        self.agent.save_agent_tree_master.assert_called_once()
        self.agent._cmd_restart_subtree.assert_called_once()
        worker.return_value.start.assert_called_once()
        self.agent.crypto_reply.assert_not_called()  # no success before verified start

    def test_readiness_monitor_start_failure_clears_pending_and_reports_uncertain(self):
        with patch.object(module.threading, "Thread") as worker:
            worker.return_value.start.side_effect = RuntimeError("thread limit")
            self.agent._cmd_hotswap_agent(self.content, {}, None)
        self.assertFalse(self.agent._hotswap_pending)
        self.assertEqual(self.node["hash_bang"], self.content["source_payload"]["sha256"])
        reply = self.agent.crypto_reply.call_args.kwargs
        self.assertEqual(reply["response_handler"], "hotswap_agent.error")
        self.assertIn("committed", reply["payload"]["message"])
        self.assertIn("could not be verified", reply["payload"]["message"])

    def test_locked_node_rejects_replace_and_config_updates(self):
        self.node["lifecycle_status"] = {"locked": True}
        self.tree.has_node.return_value = True
        self.tree.find_parent_of.return_value = {"universal_id": "parent"}
        self.agent._handle_replace_agent({"target_universal_id": "target", "new_agent": {"name": "replacement"}})
        self.agent._cmd_update_agent({"target_universal_id": "target", "config": {"x": 1}}, {})
        self.assertEqual(self.node["name"], "worker")
        self.assertNotIn("config", self.node)
        self.agent.save_agent_tree_master.assert_not_called()

    def test_injection_rejects_lifecycle_in_nested_node(self):
        self.tree.has_node.return_value = True
        self.tree.get_node.side_effect = lambda uid: {"universal_id": "parent"} if uid == "parent" else None
        subtree = {"universal_id": "new", "name": "worker", "children": [
            {"universal_id": "child", "name": "worker", "lifecycle_status": {"locked": True}}
        ]}
        result = self.agent._handle_inject_agents({"target_universal_id": "parent", "subtree": subtree}, {})
        self.assertEqual(result["status"], "error")
        self.tree.insert_node.assert_not_called()
        self.agent.save_agent_tree_master.assert_not_called()

    def test_completion_never_sends_success_when_save_fails(self):
        self.node["lifecycle_status"] = {"locked": True, "agent_status_callback": {"session_id": "s"}}
        self.tree.find_parent_of.return_value = {"universal_id": "parent"}
        self.agent.save_agent_tree_master.return_value = False
        self.agent.delegate_tree_to_agent = Mock()
        for name in ("_restart_complete_callback", "_delete_complete_callback"):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                getattr(module.Agent, name).__wrapped__(self.agent, [("target", self.node)])
        self.agent.delegate_tree_to_agent.assert_not_called()
        self.agent.crypto_reply.assert_not_called()

    def test_completion_success_and_delegation_are_deferred(self):
        self.node["lifecycle_status"] = {"locked": True, "agent_status_callback": {"session_id": "s"}}
        self.tree.find_parent_of.return_value = {"universal_id": "parent"}
        self.agent.tree_path_dict = {}
        self.agent.delegate_tree_to_agent = Mock()
        callbacks = []
        self.agent.defer_reap_side_effect = callbacks.append
        module.Agent._restart_complete_callback.__wrapped__(self.agent, [("target", self.node)])
        self.agent.commit_reap_mutation.assert_called_once()
        self.agent.crypto_reply.assert_not_called()
        self.agent.delegate_tree_to_agent.assert_not_called()
        for callback in callbacks:
            callback()
        self.agent.crypto_reply.assert_called_once()
        self.agent.delegate_tree_to_agent.assert_called_once()

    def test_mismatched_hash_or_failed_save_never_restarts(self):
        for failure in ("hash", "save"):
            with self.subTest(failure=failure):
                self.agent.crypto_reply.reset_mock()
                request = dict(self.content)
                request["source_payload"] = dict(self.content["source_payload"])
                if failure == "hash":
                    request["source_payload"]["sha256"] = "0" * 64
                self.agent.save_agent_tree_master.return_value = failure != "save"
                self.agent._cmd_hotswap_agent(request, {}, None)
                self.assertEqual(self.node["src_embed"], "old")
                self.assertEqual(self.node["hash_bang"], "oldhash")
                self.agent._cmd_restart_subtree.assert_not_called()
                self.assertEqual(self.agent.crypto_reply.call_args.kwargs["payload"]["status"], "error")
                self.assertFalse(self.agent._hotswap_pending)

    def test_wait_sends_success_only_after_readiness_check(self):
        self.agent._hotswap_pending.add("target")
        self.agent._hotswap_running = Mock(return_value=True)
        self.agent._wait_hotswap_start("target", "hash", "session", "token", time.time(), set())
        self.assertEqual(self.agent.crypto_reply.call_args.kwargs["payload"]["status"], "success")
        self.assertFalse(self.agent._hotswap_pending)
        self.agent.crypto_reply.reset_mock()
        self.agent._hotswap_pending.add("target")
        self.agent._wait_hotswap_start("target", "hash", "session", "token", time.time(), set(), timeout=0)
        self.assertEqual(self.agent.crypto_reply.call_args.kwargs["payload"]["status"], "error")

    def test_readiness_wait_allows_slow_normal_reaper_stages(self):
        self.agent._hotswap_pending.add("target")
        self.agent._hotswap_running = Mock(side_effect=[False, True])
        with patch.object(module.time, "monotonic", side_effect=[0, 0, 100]), \
             patch.object(module.time, "sleep"):
            self.agent._wait_hotswap_start("target", "hash", "session", "token", 1, set())
        self.assertEqual(self.agent.crypto_reply.call_args.kwargs["payload"]["status"], "success")

    def test_failed_restart_queue_restores_prior_source_and_reports_error(self):
        self.agent._cmd_restart_subtree.return_value = False
        with patch.object(module.threading, "Thread") as worker:
            self.agent._cmd_hotswap_agent(self.content, {}, None)
        self.assertEqual(self.node["src_embed"], "old")
        self.assertEqual(self.node["hash_bang"], "oldhash")
        self.assertEqual(self.agent.save_agent_tree_master.call_count, 2)
        self.assertEqual(self.agent.crypto_reply.call_args.kwargs["payload"]["status"], "error")
        worker.assert_not_called()

    def test_failed_restart_save_restores_prior_lifecycle_state(self):
        self.agent.path_resolution = {"comm_path": "/test"}
        self.agent.get_matrix_universal_id = Mock(return_value="matrix")
        self.agent.save_agent_tree_master.side_effect = [False, True]
        self.tree.mark_target_list.side_effect = lambda *_args, **_kwargs: self.node.update({"lifecycle_status": {"locked": True}})
        result = module.Agent._cmd_restart_subtree.__wrapped__(self.agent, {"target_universal_id": "target"}, {})
        self.assertFalse(result)
        self.assertNotIn("lifecycle_status", self.node)
        self.assertEqual(self.agent.save_agent_tree_master.call_count, 2)

    def transfer_messages(self, data, token="a" * 32):
        count = (len(data) + 8191) // 8192
        common = {"target_universal_id": "target", "session_id": "session", "token": token,
                  "size": len(data), "count": count, "sha256": hashlib.sha256(data).hexdigest()}
        # Each transfer uses a fresh token and an authenticated server challenge.
        if ("session", token) in self.agent._hotswap_challenges:
            del self.agent._hotswap_challenges[("session", token)]
        self.agent._cmd_hotswap_challenge(common, {}, None)
        common["challenge"] = self.agent.crypto_reply.call_args.kwargs["payload"]["challenge"]
        self.agent.crypto_reply.reset_mock()
        chunks = [{**common, "kind": "chunk", "index": i,
                   "data": base64.b64encode(data[i * 8192:(i + 1) * 8192]).decode()} for i in range(count)]
        return chunks, {**common, "kind": "commit"}

    def test_chunks_allow_out_of_order_commit_and_identical_duplicate(self):
        data = b"a" * 8192 + b"b" * 3000
        chunks, commit = self.transfer_messages(data)
        with patch.object(module.threading, "Timer"), patch.object(self.agent, "_cmd_hotswap_agent") as start:
            for message in (commit, chunks[1], chunks[1], chunks[0], chunks[0]):
                self.agent._cmd_hotswap_transfer(message, {}, None)
        start.assert_called_once()
        assembled = start.call_args.args[0]
        self.assertEqual(base64.b64decode(assembled["source_payload"]["payload"]), data)
        self.assertFalse(self.agent._hotswap_transfers)
        self.assertEqual(self.agent.crypto_reply.call_count, 4)
        self.assertTrue(all(call.kwargs["response_handler"] == "hotswap_agent.ack" for call in self.agent.crypto_reply.call_args_list))

    def test_conflicting_chunk_rejects_transfer_and_cannot_later_complete(self):
        chunks, commit = self.transfer_messages(b"a" * 8192 + b"b" * 4)
        altered = dict(chunks[0], data=base64.b64encode(b"x" * 8192).decode())
        with patch.object(module.threading, "Timer"), patch.object(self.agent, "_cmd_hotswap_agent") as start:
            for message in (chunks[0], altered, commit, chunks[1]):
                self.agent._cmd_hotswap_transfer(message, {}, None)
        start.assert_not_called()
        self.assertEqual(self.agent.crypto_reply.call_count, 2)
        self.assertEqual(self.agent.crypto_reply.call_args.kwargs["payload"]["status"], "error")
        self.assertFalse(self.agent._hotswap_transfers)

    def test_duplicate_commit_is_acknowledged_but_never_restarts_twice(self):
        chunks, commit = self.transfer_messages(b"x")
        with patch.object(module.threading, "Timer"), patch.object(self.agent, "_cmd_hotswap_agent") as start:
            for message in (chunks[0], commit, commit):
                self.agent._cmd_hotswap_transfer(message, {}, None)
        start.assert_called_once()
        self.assertEqual(self.agent.crypto_reply.call_count, 3)
        self.assertTrue(all(call.kwargs["response_handler"] == "hotswap_agent.ack" for call in self.agent.crypto_reply.call_args_list))

    def test_over_64k_source_stages_only_after_chunked_assembly(self):
        source = b"x = 1\n" + b"#" * 66012
        chunks, commit = self.transfer_messages(source)
        with patch.object(module.threading, "Timer"), patch.object(module.threading, "Thread") as worker:
            for message in [*chunks, commit]:
                self.agent._cmd_hotswap_transfer(message, {}, None)
        self.assertEqual(base64.b64decode(self.node["src_embed"]), source)
        self.assertEqual(self.node["hash_bang"], hashlib.sha256(source).hexdigest())
        self.agent._cmd_restart_subtree.assert_called_once()
        worker.return_value.start.assert_called_once()

    def test_large_direct_packet_remains_limited(self):
        source = b"x = 1\n" + b"#" * 66012
        request = dict(self.content, source_payload={"payload": base64.b64encode(source).decode(),
                                                     "sha256": hashlib.sha256(source).hexdigest()})
        self.agent._cmd_hotswap_agent(request, {}, None)
        self.agent._cmd_restart_subtree.assert_not_called()
        self.assertEqual(self.agent.crypto_reply.call_args.kwargs["payload"]["status"], "error")

    def test_legacy_source_replace_never_reports_success(self):
        self.agent._cmd_replace_source({"target_agent_name": "../outside", "payload": {
            "session_id": "session", "token": "token", "source": "ignored"}}, {}, None)
        reply = self.agent.crypto_reply.call_args.kwargs
        self.assertEqual(reply["response_handler"], "replace_agent_source.error")
        self.assertEqual(reply["payload"]["status"], "error")

    def test_incomplete_transfer_expires_and_capacity_is_bounded(self):
        chunks, _ = self.transfer_messages(b"a" * 9000)
        with patch.object(module.threading, "Timer"):
            self.agent._cmd_hotswap_transfer(chunks[0], {}, None)
            key = ("session", "a" * 32)
            created = self.agent._hotswap_transfers[key]["created"]
            self.agent._expire_hotswap_transfer(key, created)
            self.assertFalse(self.agent._hotswap_transfers)
            self.assertEqual(self.agent.crypto_reply.call_args.kwargs["payload"]["status"], "error")
            for n in range(9):
                item, _ = self.transfer_messages(b"x", token=f"{n:032x}")
                self.agent._cmd_hotswap_transfer(item[0], {}, None)
            self.assertEqual(len(self.agent._hotswap_transfers), 8)

    def test_malformed_unhashable_transfer_identity_is_rejected_without_exception(self):
        self.agent._cmd_hotswap_transfer({"session_id": [], "token": "a" * 32}, {}, None)
        self.assertFalse(self.agent._hotswap_transfers)

    def test_direct_request_cannot_replay_after_completion_or_clock_rollback(self):
        with patch.object(module.threading, "Thread"), patch.object(module.time, "monotonic", return_value=100):
            self.agent._cmd_hotswap_agent(self.content, {}, None)
        self.agent._hotswap_pending.clear()
        self.agent._cmd_restart_subtree.reset_mock()
        with patch.object(module.time, "monotonic", return_value=1):
            self.agent._cmd_hotswap_agent(self.content, {}, None)
        self.agent._cmd_restart_subtree.assert_not_called()
        self.agent.crypto_reply.assert_not_called()

    def test_old_challenge_cannot_replay_after_matrix_process_restart(self):
        chunks, _ = self.transfer_messages(b"a" * 9000)
        old = dict(chunks[0])
        self.agent._hotswap_challenges.clear()  # a new Matrix process
        self.agent._hotswap_transfers.clear()
        self.agent._hotswap_closed.clear()
        challenge_request = {k: old[k] for k in ("session_id", "token", "target_universal_id", "size", "count", "sha256")}
        with patch.object(module.secrets, "token_hex", return_value="b" * 64):
            self.agent._cmd_hotswap_challenge(challenge_request, {}, None)
        self.agent.crypto_reply.reset_mock()
        with patch.object(module.threading, "Timer"):
            self.agent._cmd_hotswap_transfer(old, {}, None)
        self.assertFalse(self.agent._hotswap_transfers)
        self.agent.crypto_reply.assert_not_called()

    def test_stale_chunk_cannot_abort_active_fresh_transfer(self):
        chunks, commit = self.transfer_messages(b"a" * 8192 + b"b")
        stale = dict(chunks[0], challenge="0" * 64)
        with patch.object(module.threading, "Timer"), patch.object(self.agent, "_cmd_hotswap_agent") as start:
            self.agent._cmd_hotswap_transfer(chunks[0], {}, None)
            self.agent.crypto_reply.reset_mock()
            self.agent._cmd_hotswap_transfer(stale, {}, None)
            self.agent.crypto_reply.assert_not_called()
            self.assertTrue(self.agent._hotswap_transfers)
            self.agent._cmd_hotswap_transfer(chunks[1], {}, None)
            self.agent._cmd_hotswap_transfer(commit, {}, None)
        start.assert_called_once()

    def test_challenge_retry_is_idempotent(self):
        self.agent._cmd_hotswap_challenge(self.content, {}, None)
        self.assertEqual(self.agent.crypto_reply.call_args.kwargs["payload"]["challenge"], self.content["challenge"])

    def test_challenge_capacity_fails_closed_without_evicting_tokens(self):
        self.agent._hotswap_challenges = {(f"s{i}", "a" * 32): {"closed": True} for i in range(4096)}
        self.agent._cmd_hotswap_challenge(self.content, {}, None)
        self.assertEqual(len(self.agent._hotswap_challenges), 4096)
        self.assertEqual(self.agent.crypto_reply.call_args.kwargs["payload"]["status"], "error")

    def test_old_signed_source_fails_after_real_process_restart_with_clock_rollback(self):
        script = textwrap.dedent('''
            import base64, hashlib, importlib.util, json, os, sys, threading
            from unittest.mock import Mock, patch
            spec = importlib.util.spec_from_file_location("matrix_hotswap_restart", sys.argv[1])
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            agent = module.Agent.__new__(module.Agent)
            agent._hotswap_lock = threading.Lock()
            agent._hotswap_challenges = {}
            agent._hotswap_pending = set()
            agent.tree_node = {}
            agent.log = Mock()
            agent.crypto_reply = Mock(return_value=True)
            agent._cmd_restart_subtree = Mock()
            source = b"print(1)\\n"
            sha = hashlib.sha256(source).hexdigest()
            request = {"session_id":"session", "token":"a"*32, "target_universal_id":"target",
                       "size":len(source), "count":1, "sha256":sha}
            # The wall clock moves backwards between the two process runs.
            with patch.object(module.time, "time", return_value=float(sys.argv[2])):
                agent._cmd_hotswap_challenge(request, {}, None)
            fresh = agent.crypto_reply.call_args.kwargs["payload"]["challenge"]
            if len(sys.argv) > 3:
                old = dict(request, challenge=sys.argv[3], source_payload={
                    "payload":base64.b64encode(source).decode(), "sha256":sha})
                agent.crypto_reply.reset_mock()
                module.Agent._cmd_hotswap_agent.__wrapped__(agent, old, {}, None)
                result = "ignored" if not agent.crypto_reply.called else "replied"
                assert not agent._cmd_restart_subtree.called
            else:
                result = None
            print(json.dumps({"challenge":fresh, "result":result}))
        ''')
        env = dict(os.environ, SITE_ROOT=str(ROOT / "matrixos"), AGENT_PATH=str(ROOT / "matrixos/agents/python_core"))
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "matrixos"), env.get("PYTHONPATH", "")])
        agent_file = str(ROOT / "matrixos/agents/python_core/matrix/matrix.py")
        def run(clock, *args):
            completed = subprocess.run([sys.executable, "-B", "-c", script, agent_file, str(clock), *args],
                                       env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       encoding="utf-8", errors="replace", timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stdout)
            return json.loads(completed.stdout.splitlines()[-1])
        previous = run(200)
        restarted = run(100, previous["challenge"])
        self.assertNotEqual(previous["challenge"], restarted["challenge"])
        self.assertEqual(restarted["result"], "ignored")

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux path handles required")
    def test_readiness_requires_new_process_matching_hash_and_own_ready_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            boot = Path(temp) / "universes/runtime/test/20261111_123456"
            pod = boot / "pod/pod1"
            pod.mkdir(parents=True)
            requested = time.time() - 5
            started = requested + 1
            (pod / "boot.json").write_text(json.dumps({"universal_id": "target", "pid": 123,
                                                        "process_started_at": started, "source_sha256": "hash"}))
            ready = {"universal_id": "target", "pid": 123, "process_started_at": started, "source_sha256": "hash"}
            (pod / "ready.json").write_text(json.dumps(ready))
            self.agent.path_resolution = {"install_path": temp, "reboot_uuid": "20261111_123456"}
            self.agent._hotswap_processes = Mock(return_value={(123, started)})
            self.assertTrue(self.agent._hotswap_running("target", "hash", requested, set()))
            self.assertFalse(self.agent._hotswap_running("target", "wrong", requested, set()))
            self.assertFalse(self.agent._hotswap_running("target", "hash", requested, {(123, started)}))
            (pod / "ready.json").write_text(json.dumps({**ready, "pid": 122}))
            self.assertFalse(self.agent._hotswap_running("target", "hash", requested, set()))


if __name__ == "__main__":
    unittest.main()
