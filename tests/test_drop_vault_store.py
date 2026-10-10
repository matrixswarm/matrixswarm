"""Synthetic-only encrypted clipboard storage and protocol regression tests."""
import ast
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import time
import traceback
import unittest
from unittest.mock import Mock, patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
sys.path.insert(0, str(ROOT / "matrixos/agents/python_core"))
from core.python_core.mixin.encrypted_state import EncryptedStateMixin, EncryptedStateError
from core.python_core.agent_progress import AgentProgress, REASONS, failure_reason
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from drop_vault.store import DropStore, DropError, CHUNK_BYTES, MAX_OBJECT_BYTES


class Persistence(EncryptedStateMixin):
    def __init__(self, root, key=b"k"*32, uid="drop-a"):
        self.command_line_args = {"universal_id": uid, "universe": "test-universe"}
        self.path_resolution = {"root_path": str(root)}
        self.tree_node = {"config": {"security": {"persistent_state": {
            "state_id": "test-clipboard", "algorithm": "AES-256-GCM", "key_version": 1,
            "key": base64.b64encode(key).decode("ascii")}}}}
        self.init_encrypted_state(namespace="drop_vault")


def begin(store, data=b"synthetic secret", **overrides):
    values = dict(owner="client-a", object_id=uuid.uuid4().hex, kind="text", title="Synthetic title",
                  filename="", notes="Synthetic notes", size=len(data), sha256=hashlib.sha256(data).hexdigest())
    values.update(overrides)
    store.begin(**values)
    return values


def upload(store, data=b"synthetic secret", **overrides):
    values = begin(store, data, **overrides)
    for offset in range(0, len(data), CHUNK_BYTES):
        store.chunk(values["owner"], values["object_id"], offset,
                    base64.b64encode(data[offset:offset+CHUNK_BYTES]).decode())
    return store.commit(values["owner"], values["object_id"])["entry"]


def load_agent_class():
    path = ROOT / "matrixos/agents/python_core/drop_vault/drop_vault.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "Agent")
    cls.bases = []
    scope = dict(IdentityObject=IdentityObject, DropError=DropError, re=re,
                 hashlib=hashlib, traceback=traceback, time=time,
                 AgentProgress=AgentProgress, REASONS=REASONS, failure_reason=failure_reason)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), "exec"), scope)
    return scope["Agent"]


def initialize_progress(agent, root):
    agent.path_resolution = {"comm_path_resolved": str(root)}
    agent.progress = AgentProgress(agent, {
        "inbox_setup": (None, 120),
        **{"inbox_" + operation: (None, 120) for operation in
           ("list", "read", "begin", "chunk", "commit", "cancel", "delete")},
        "inbox_cleanup": (30, 120), "inbox_reply": (None, 30),
    })


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.persistence = Persistence(self.temp.name)
        self.store = DropStore(self.persistence)
        self.addCleanup(self.store.close)

    def test_encrypted_catalogue_and_separate_blob_survive_redeployment(self):
        entry = upload(self.store, title="SECRET-TITLE", notes="SECRET-NOTES")
        self.assertEqual(entry["size"], len(b"synthetic secret"))
        for path in self.persistence._encrypted_state_root.rglob("*.aes"):
            data = path.read_bytes()
            for secret in (b"synthetic secret", b"SECRET-TITLE", b"SECRET-NOTES", b"CREATE TABLE", b"SQLite format"):
                self.assertNotIn(secret, data)
        self.assertEqual(len(list(self.persistence._encrypted_state_root.rglob("*.aes"))), 2)
        self.store.close()
        reopened = DropStore(Persistence(self.temp.name, uid="new-deployment-agent"))
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.listing()["total_items"], 1)
        self.assertEqual(base64.b64decode(reopened.read(entry["id"], 0)["data"]), b"synthetic secret")

    def test_wrong_key_or_tamper_fails_without_reset(self):
        upload(self.store)
        self.store.close()
        with self.assertRaises(EncryptedStateError):
            DropStore(Persistence(self.temp.name, key=b"z"*32))
        path = self.persistence._encrypted_state_root / "catalog.json.aes"
        envelope = json.loads(path.read_text())
        ciphertext = bytearray(base64.b64decode(envelope["ciphertext"]))
        ciphertext[-1] ^= 1
        envelope["ciphertext"] = base64.b64encode(ciphertext).decode()
        path.write_text(json.dumps(envelope))
        with self.assertRaises(EncryptedStateError):
            DropStore(Persistence(self.temp.name))
        self.assertTrue(path.exists())

    def test_writer_lock_prevents_overlapping_process_instances(self):
        with self.assertRaises(DropError):
            DropStore(Persistence(self.temp.name))

    def test_uncommitted_upload_not_visible_and_restart_discards_it(self):
        begin(self.store)
        self.assertEqual(self.store.listing()["total_items"], 0)
        self.store.close()
        reopened = DropStore(Persistence(self.temp.name))
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.uploads, {})

    def test_chunk_and_commit_replays_do_not_duplicate(self):
        values = begin(self.store)
        encoded = base64.b64encode(b"synthetic secret").decode()
        for _ in range(2):
            self.assertEqual(self.store.chunk("client-a", values["object_id"], 0, encoded)["offset"], 16)
        for _ in range(2):
            self.store.commit("client-a", values["object_id"])
        self.assertEqual(self.store.listing()["total_items"], 1)
        self.assertTrue(self.store.begin(**values)["committed"])

    def test_owner_isolation_and_checksum_mismatch(self):
        values = begin(self.store, sha256="0"*64)
        with self.assertRaises(DropError):
            self.store.chunk("other", values["object_id"], 0, "YQ==")
        self.store.chunk("client-a", values["object_id"], 0, base64.b64encode(b"synthetic secret").decode())
        with self.assertRaises(DropError):
            self.store.commit("client-a", values["object_id"])
        self.assertEqual(self.store.listing()["total_items"], 0)

    def test_catalogue_save_failure_rolls_back_and_retry_recovers(self):
        values = begin(self.store, b"")
        with patch.object(self.store, "_save_catalog", side_effect=OSError("TEST disk failure")):
            with self.assertRaises(OSError):
                self.store.commit("client-a", values["object_id"])
        self.assertEqual(self.store.listing()["total_items"], 0)
        self.store.commit("client-a", values["object_id"])
        self.assertEqual(self.store.listing()["total_items"], 1)

    def test_blob_save_failure_never_publishes_catalogue_entry(self):
        values = begin(self.store, b"")
        with patch.object(self.persistence, "save_encrypted_state", side_effect=OSError("TEST")):
            with self.assertRaises(OSError):
                self.store.commit("client-a", values["object_id"])
        self.assertEqual(self.store.listing()["total_items"], 0)

    def test_filename_paths_sizes_and_unknown_kind_rejected(self):
        for params in ({"object_id": "../../file"}, {"kind": "shell"}, {"size": True},
                       {"size": MAX_OBJECT_BYTES+1}, {"kind": "file", "filename": "../secret"},
                       {"notes": "a"*4097}):
            with self.subTest(params=params), self.assertRaises(DropError):
                begin(self.store, **params)
        entry = upload(self.store, b"\x00\xff", kind="file", filename="binary.dat")
        self.assertEqual(base64.b64decode(self.store.read(entry["id"], 0)["data"]), b"\x00\xff")

    def test_invalid_utf8_paste_is_not_published(self):
        with self.assertRaises(DropError):
            upload(self.store, b"\xff")
        self.assertEqual(self.store.listing()["total_items"], 0)

    def test_one_mib_limit_is_enforced_for_files_and_utf8_pastes(self):
        self.assertEqual(MAX_OBJECT_BYTES, 1024 * 1024)
        for kind, filename in (("text", ""), ("file", "small.bin")):
            with self.subTest(kind=kind):
                data = ("é" * (MAX_OBJECT_BYTES // 2)).encode("utf-8")
                entry = upload(self.store, data, kind=kind, filename=filename)
                downloaded = b"".join(base64.b64decode(self.store.read(entry["id"], offset)["data"])
                                      for offset in range(0, len(data), CHUNK_BYTES))
                self.assertEqual(downloaded, data)
                with self.assertRaises(DropError):
                    begin(self.store, data + b"x", kind=kind, filename=filename)
        self.assertEqual(self.store.listing()["max_object_bytes"], MAX_OBJECT_BYTES)
        self.assertEqual(self.store.listing()["total_items"], 2)
        self.assertEqual(self.store.uploads, {})

    def test_expired_upload_and_concurrent_upload_limit(self):
        values = [begin(self.store) for _ in range(4)]
        with self.assertRaises(DropError):
            begin(self.store)
        self.store.uploads[values[0]["object_id"]]["expires"] = 0
        self.store.maintain()
        begin(self.store)
        with self.assertRaises(DropError):
            self.store.commit("client-a", values[0]["object_id"])

    def test_paging_and_concurrent_clients_do_not_lose_entries(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda i: upload(self.store, str(i).encode(), owner=f"client-{i%2}"), range(55)))
        first = self.store.listing()
        second = self.store.listing(first["next_before"])
        third = self.store.listing(second["next_before"])
        self.assertEqual(len(first["entries"]), 20)
        self.assertEqual(len(second["entries"]), 20)
        self.assertEqual(len(third["entries"]), 15)
        self.assertEqual(len({x["id"] for page in (first, second, third) for x in page["entries"]}), 55)
        self.assertNotIn("owner", first["entries"][0])

    def test_delete_removes_listing_blob_and_cached_bytes(self):
        entry = upload(self.store)
        self.store.read(entry["id"], 0)
        result = self.store.delete(entry["id"])
        self.assertFalse(result["cleanup_pending"])
        self.assertNotIn(entry["id"], self.store.cache)
        self.assertFalse((self.persistence._encrypted_state_root / "objects" / (entry["id"]+".json.aes")).exists())
        with self.assertRaises(DropError):
            self.store.read(entry["id"], 0)

    def test_failed_delete_persistence_does_not_remove_object(self):
        entry = upload(self.store)
        with patch.object(self.store, "_save_catalog", side_effect=OSError("TEST")):
            with self.assertRaises(OSError):
                self.store.delete(entry["id"])
        self.assertEqual(self.store.read(entry["id"], 0)["entry"]["id"], entry["id"])

    def test_blob_cleanup_failure_has_durable_retry_receipt(self):
        entry = upload(self.store)
        with patch.object(self.persistence, "delete_encrypted_state", side_effect=OSError("TEST")):
            self.assertTrue(self.store.delete(entry["id"])["cleanup_pending"])
            self.assertEqual(self.store.listing()["pending_deletions"], 1)
            self.assertEqual(self.store.cleanup_error, "OSError")
            with self.assertRaises(DropError):
                begin(self.store, object_id=entry["id"])
        self.store.close()
        reopened = DropStore(Persistence(self.temp.name))
        self.addCleanup(reopened.close)
        reopened.collect_garbage()
        self.assertEqual(reopened.db.execute("SELECT COUNT(*) FROM garbage").fetchone()[0], 0)
        self.assertEqual(reopened.listing()["total_items"], 0)

    def test_sql_metacharacters_are_data_not_queries(self):
        title = "x'); DROP TABLE objects; --"
        upload(self.store, title=title)
        self.store.close()
        reopened = DropStore(Persistence(self.temp.name))
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.listing()["entries"][0]["title"], title)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        cls = load_agent_class()
        self.agent = cls.__new__(cls)
        self.agent.command_line_args = {"universal_id": "drop-a"}
        initialize_progress(self.agent, temporary.name)
        self.agent.get_matrix_universal_id = lambda: "matrix"
        self.agent._rpc_role = "hive.rpc"
        self.agent.store = Mock()
        self.agent.store.listing.return_value = {"entries": []}
        self.agent.crypto_reply = Mock()
        self.agent.log = Mock()
        self.request = dict(target_universal_id="drop-a", session_id="session-a", token="token-a",
                            request_id="request-a", operation="list", args={})
        self.identity = IdentityObject(True, "matrix")

    def test_authentication_exact_target_and_callback_identity(self):
        for identity in (None, IdentityObject(False, "matrix"), IdentityObject(True, "other")):
            self.agent.cmd_request(self.request, None, identity)
        self.agent.cmd_request(dict(self.request, target_universal_id="other"), None, self.identity)
        self.agent.store.listing.assert_not_called()
        self.agent.cmd_request(self.request, None, self.identity)
        result = self.agent.crypto_reply.call_args.kwargs
        self.assertEqual(result["payload"]["token"], "token-a")
        self.assertEqual(result["response_handler"], "drop_vault.result")
        self.assertTrue(result["quiet"])

    def test_successful_list_does_not_log_every_poll(self):
        self.agent.cmd_request(self.request, None, self.identity)
        self.agent.log.assert_not_called()
        self.agent.crypto_reply.assert_called_once()

    def test_unknown_operation_and_parameters_do_not_dispatch(self):
        for request in (dict(self.request, operation="shell"), dict(self.request, args={"path": "secrets"}),
                        dict(self.request, operation="read", args={})):
            self.agent.cmd_request(request, None, self.identity)
            self.assertFalse(self.agent.crypto_reply.call_args.kwargs["payload"]["ok"])
        self.agent.store.listing.assert_not_called()

    def test_storage_exception_messages_never_leak_contents(self):
        self.agent.store.listing.side_effect = OSError("SYNTHETIC-SENSITIVE-CONTENT")
        self.agent.cmd_request(self.request, None, self.identity)
        self.assertNotIn("SYNTHETIC-SENSITIVE-CONTENT", str(self.agent.log.call_args))
        self.assertNotIn("SYNTHETIC-SENSITIVE-CONTENT", str(self.agent.crypto_reply.call_args))

    def test_unqueued_session_reply_is_logged_without_content(self):
        self.agent.crypto_reply.return_value = False
        self.agent.store.listing.return_value = {"entries": [], "marker": "SYNTHETIC-PRIVATE-PASTE"}
        self.agent.cmd_request(self.request, None, self.identity)
        self.assertTrue(any("Session reply was not queued" in str(call)
                            for call in self.agent.log.call_args_list))
        self.assertNotIn("SYNTHETIC-PRIVATE-PASTE", str(self.agent.log.call_args_list))


if __name__ == "__main__":
    unittest.main()
