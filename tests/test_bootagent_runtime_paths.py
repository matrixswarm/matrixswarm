import os
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
from core.python_core.boot_agent import BootAgent
from core.python_core.safe_paths import runtime_directory
from core.python_core.swarm_session_root import SwarmSessionRoot


@unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux openat2")
class BootAgentRuntimePathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        SwarmSessionRoot("u", str(self.base), "boot")
        with runtime_directory(str(self.base), "u", "boot", "comm") as root_fd:
            self.root_fd = os.dup(root_fd)
        self.addCleanup(os.close, self.root_fd)
        with runtime_directory(str(self.base), "u", "boot", "comm", child="agent", create_child=True) as fd:
            self.fd = os.dup(fd)
        self.addCleanup(os.close, self.fd)
        self.agent = BootAgent.__new__(BootAgent)
        self.agent._runtime_comm_fd = self.fd
        self.agent._runtime_comm_root_fd = self.root_fd
        self.agent.path_resolution = {"install_path": str(self.base), "reboot_uuid": "boot",
                                      "comm_path": str(self.base / "universes/runtime/u/boot/comm"),
                                      "comm_path_resolved": str(self.base / "universes/runtime/u/boot/comm/agent")}
        self.agent.command_line_args = {"universe": "u", "universal_id": "agent"}
        self.agent.debug = SimpleNamespace(is_enabled=lambda: False)
        self.messages = []
        self.agent.log = lambda *args, **kwargs: self.messages.append(str(args[0]) if args else "")

    def test_heartbeat_stays_with_pinned_agent_after_path_swap(self):
        agent_dir = Path(self.agent.path_resolution["comm_path_resolved"])
        original = agent_dir.with_name("original")
        outside = self.base / "outside"
        outside.mkdir()
        agent_dir.rename(original)
        agent_dir.symlink_to(outside, target_is_directory=True)
        emit = self.agent.check_for_thread_poke("worker", timeout=60, emit_to_file_interval=0)
        emit()
        self.assertEqual(len(list((original / "hello.moto").glob("poke.worker.*"))), 1)
        self.assertEqual(list(outside.iterdir()), [])

    def test_heartbeat_refuses_linked_zone_and_marker(self):
        agent_dir = Path(self.agent.path_resolution["comm_path_resolved"])
        outside = self.base / "outside"
        outside.mkdir()
        (agent_dir / "hello.moto").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.agent.check_for_thread_poke("worker", emit_to_file_interval=0)()
        self.assertEqual(list(outside.iterdir()), [])
        (agent_dir / "hello.moto").unlink()
        (agent_dir / "hello.moto").mkdir()
        target = outside / "valuable"
        target.write_text("keep")
        (agent_dir / "hello.moto/poke.worker").symlink_to(target)
        with self.assertRaises(ValueError):
            self.agent.emit_dead_poke("worker", "failure")
        self.assertEqual(target.read_text(), "keep")

    def test_singleton_accepts_regular_die_but_rejects_symlink(self):
        incoming = Path(self.agent.path_resolution["comm_path_resolved"]) / "incoming"
        incoming.mkdir()
        target = self.base / "outside"
        target.write_text("keep")
        self.agent.shutdown_now = lambda reason: None
        for linked in (True, False):
            self.messages.clear()
            self.agent.running = True
            marker = incoming / "die"
            if linked:
                marker.symlink_to(target)
            else:
                marker.write_text("die")
            with patch("core.python_core.boot_agent.DuplicateProcessCheck.get_self_job_label", return_value="u:agent"), \
                 patch("core.python_core.boot_agent.DuplicateProcessCheck.check_all_duplicate_risks", return_value=False), \
                 patch("core.python_core.boot_agent.interruptible_sleep", side_effect=lambda agent, _: setattr(agent, "running", False)):
                self.agent.enforce_singleton()
            self.assertEqual(any("die.cookie ingested" in m for m in self.messages), not linked)
            self.assertEqual(target.read_text(), "keep")
            marker.unlink()

    def test_packet_listener_pins_receive_and_removal_to_same_directory(self):
        agent_dir = Path(self.agent.path_resolution["comm_path_resolved"])
        original = agent_dir.with_name("original")
        outside = self.base / "outside"
        (outside / "incoming").mkdir(parents=True)
        (outside / "incoming/pk_message.json").write_text(json.dumps({"handler": "cmd_fixture", "content": {"source": "outside"}}))
        received = []
        closed = []

        class Receiver:
            def set_location(self, *_): return self
            def set_address(self, *_): return self
            def set_drop_zone(self, *_): return self
            def set_directory_fd(self, fd): self.fd = os.dup(fd); return self
            def set_identifier(self, name): self.name = name; return self
            def set_packet(self, *_): return self
            def receive(self):
                fd = os.open(self.name, os.O_RDONLY, dir_fd=self.fd)
                with os.fdopen(fd, "r") as file:
                    data = json.load(file)
                return SimpleNamespace(get_packet=lambda: data)
            def get_identity(self): return None
            def get_error_success(self): return False
            def close(self): os.close(self.fd); closed.append(True)

        self.agent.FootballType = SimpleNamespace(CATCH="catch")
        self.agent.get_football = lambda **kwargs: object()
        self.agent.get_reception_agent = lambda *args, **kwargs: Receiver()
        self.agent.get_delivery_packet = lambda *args, **kwargs: SimpleNamespace(set_packet=lambda packet: None)
        self.agent.cmd_fixture = lambda content, packet, identity: received.append(content["source"])
        self.agent._emit_beacon_packet_listener = lambda: None
        self.agent.running = True
        calls = []
        def sleep(agent, _):
            calls.append(True)
            if len(calls) == 1:
                agent_dir.rename(original)
                agent_dir.symlink_to(outside, target_is_directory=True)
                (original / "incoming/pk_message.json").write_text(json.dumps({"handler": "cmd_fixture", "content": {"source": "original"}}))
            else:
                agent.running = False
        with patch("core.python_core.boot_agent.interruptible_sleep", side_effect=sleep):
            self.agent.packet_listener()
        self.assertEqual(received, ["original"])
        self.assertEqual(closed, [True])
        self.assertFalse((original / "incoming/pk_message.json").exists())
        self.assertTrue((outside / "incoming/pk_message.json").exists())

    def test_packet_removal_preserves_replaced_entry(self):
        with self.agent._own_comm_zone("incoming", create=True) as fd:
            incoming = Path(self.agent.path_resolution["comm_path_resolved"]) / "incoming"
            packet = incoming / "pk_message.json"
            packet.write_text("original")
            identity = self.agent._regular_entry_identity(fd, packet.name)
            replacement = incoming / "replacement"
            replacement.write_text("new")
            replacement.replace(packet)
            self.assertFalse(self.agent._unlink_received_entry(fd, packet.name, identity))
            self.assertEqual(packet.read_text(), "new")

    def test_worker_config_receive_and_removal_stay_on_pinned_directory(self):
        agent_dir = Path(self.agent.path_resolution["comm_path_resolved"])
        original = agent_dir.with_name("original")
        outside = self.base / "outside"
        (outside / "config").mkdir(parents=True)
        (outside / "config/change.json").write_text('{"source":"outside"}')
        seen, closed = [], []
        class Receiver:
            def set_location(self, *_): return self
            def set_address(self, *_): return self
            def set_drop_zone(self, *_): return self
            def set_directory_fd(self, fd): self.fd = os.dup(fd); return self
            def set_identifier(self, name): self.name = name; return self
            def set_packet(self, *_): return self
            def receive(self):
                with os.fdopen(os.open(self.name, os.O_RDONLY, dir_fd=self.fd), "r") as file:
                    data = json.load(file)
                return SimpleNamespace(get_packet=lambda: data)
            def get_identity(self): return None
            def get_error_success(self): return False
            def close(self): os.close(self.fd); closed.append(True)
        def get_token(timeout):
            agent_dir.rename(original)
            agent_dir.symlink_to(outside, target_is_directory=True)
            (original / "config/change.json").write_text('{"source":"original"}')
            return True
        def worker(config, identity):
            seen.append(config.get("source"))
            self.agent.running = False
        self.agent.FootballType = SimpleNamespace(CATCH="catch")
        self.agent.get_football = lambda **kwargs: object()
        self.agent.get_reception_agent = lambda *args, **kwargs: Receiver()
        self.agent.get_delivery_packet = lambda *args, **kwargs: object()
        self.agent.throttle_queue = SimpleNamespace(get=get_token)
        self.agent.worker = worker
        self.agent.running = True
        with patch("core.python_core.boot_agent.interruptible_sleep", return_value=None):
            self.agent._throttled_worker_wrapper()
        self.assertEqual(seen, ["original"])
        self.assertEqual(closed, [True])
        self.assertFalse((original / "config/change.json").exists())
        self.assertTrue((outside / "config/change.json").exists())

    def test_save_directive_reports_delivery_agent_failure(self):
        class Packet:
            def set_data(self, data): pass
        class Delivery:
            def __init__(self, failed): self.failed = failed
            def set_location(self, *_): return self
            def set_identifier(self, *_): return self
            def set_metadata(self, *_): return self
            def set_address(self, *_): return self
            def set_drop_zone(self, *_): return self
            def set_packet(self, *_): return self
            def deliver(self): return self
            def get_error_success(self): return int(self.failed)
            def get_error_success_msg(self): return "write refused" if self.failed else "OK"
        self.agent.encryption_enabled = False
        self.agent.get_delivery_packet = lambda *args, **kwargs: Packet()
        path = {"path": "/fixture", "name": "agent_tree.json", "address": "agent", "drop": "directive"}
        for failed in (False, True):
            self.agent.get_delivery_agent = lambda *args, **kwargs: Delivery(failed)
            self.assertEqual(self.agent.save_directive(path, {"test": True}, object()), not failed)
        self.assertTrue(any("write refused" in message for message in self.messages))

    def test_save_directive_pins_own_comm_root_for_delivery(self):
        seen, closed = [], []
        class Packet:
            def set_data(self, data): pass
        class Delivery:
            def set_location(self, *_): return self
            def set_location_fd(self, fd): seen.append(os.fstat(fd).st_ino); return self
            def set_identifier(self, *_): return self
            def set_metadata(self, *_): return self
            def set_address(self, *_): return self
            def set_drop_zone(self, *_): return self
            def set_packet(self, *_): return self
            def deliver(self): return self
            def get_error_success(self): return 0
            def close(self): closed.append(True)
        self.agent.encryption_enabled = False
        self.agent.get_delivery_packet = lambda *args, **kwargs: Packet()
        self.agent.get_delivery_agent = lambda *args, **kwargs: Delivery()
        path = {"path": self.agent.path_resolution["comm_path"], "name": "agent_tree.json", "address": "agent", "drop": "directive"}
        self.assertTrue(self.agent.save_directive(path, {"test": True}, object()))
        self.assertEqual(seen, [os.fstat(self.root_fd).st_ino])
        self.assertEqual(closed, [True])

    def test_respawn_checks_and_cleanup_stay_inside_pinned_comm_root(self):
        comm = self.base / "universes/runtime/u/boot/comm"
        child = comm / "child"
        (child / "hello.moto").mkdir(parents=True)
        (child / "incoming").mkdir()
        poke = child / "hello.moto/poke.worker.1.0.0"
        poke.write_text("")
        os.utime(poke, (1, 1))
        (child / "incoming/punji").write_text("ouch")
        with patch("core.python_core.boot_agent.find_jobs_by_prefix", return_value=[]):
            self.assertTrue(self.agent.clear_to_spawn("u", "child"))
        self.assertFalse(poke.exists())
        self.assertFalse((child / "incoming/punji").exists())
        outside = self.base / "outside"
        (outside / "hello.moto").mkdir(parents=True)
        (outside / "hello.moto/poke.worker.1.0.0").write_text("keep")
        child.rename(comm / "saved")
        child.symlink_to(outside, target_is_directory=True)
        with patch("core.python_core.boot_agent.find_jobs_by_prefix", return_value=[]):
            self.assertFalse(self.agent.clear_to_spawn("u", "child"))
        self.assertEqual((outside / "hello.moto/poke.worker.1.0.0").read_text(), "keep")

    def test_pass_packet_reads_identity_and_sends_from_pinned_root(self):
        comm = self.base / "universes/runtime/u/boot/comm"
        codex = comm / "child/codex"
        codex.mkdir(parents=True)
        (codex / "signed_public_key.json").write_text('{"identity":"original"}')
        seen, closed = [], []
        class Football:
            def load_identity_file(self, **kwargs):
                seen.append(kwargs["vault"]["identity"])
                return True
        class Delivery:
            def set_location(self, *_): return self
            def set_location_fd(self, fd):
                self.fd = os.dup(fd)
                return self
            def set_address(self, *_): return self
            def set_drop_zone(self, *_): return self
            def set_packet(self, *_): return self
            def deliver(self):
                seen.append(os.fstat(self.fd).st_ino == os.fstat(self_root_fd).st_ino)
                return self
            def get_error_success(self): return 0
            def close(self): os.close(self.fd); closed.append(True)
        self_root_fd = self.root_fd
        self.agent.FootballType = SimpleNamespace(PASS="pass")
        self.agent.get_football = lambda **kwargs: Football()
        self.agent.get_delivery_agent = lambda *args, **kwargs: Delivery()
        self.assertTrue(self.agent.pass_packet(object(), "child"))
        self.assertEqual(seen, ["original", True])
        self.assertEqual(closed, [True])
        outside = self.base / "outside"
        outside.write_text('{"identity":"outside"}')
        (codex / "signed_public_key.json").unlink()
        (codex / "signed_public_key.json").symlink_to(outside)
        self.assertFalse(self.agent.pass_packet(object(), "child"))
        self.assertEqual(outside.read_text(), '{"identity":"outside"}')

    def test_load_directive_pins_own_directory_before_receiving(self):
        agent_dir = Path(self.agent.path_resolution["comm_path_resolved"])
        (agent_dir / "directive").mkdir()
        tree = {"universal_id": "agent", "name": "fixture", "children": []}
        (agent_dir / "directive/agent_tree.json").write_text(json.dumps({"agent_tree": tree}))
        outside = self.base / "outside"
        (outside / "directive").mkdir(parents=True)
        (outside / "directive/agent_tree.json").write_text(json.dumps({"agent_tree": {"universal_id": "wrong", "name": "wrong"}}))
        original = agent_dir.with_name("original")
        class Receiver:
            def set_location(self, *_): return self
            def set_directory_fd(self, fd):
                self.fd = os.dup(fd)
                agent_dir.rename(original)
                agent_dir.symlink_to(outside, target_is_directory=True)
                return self
            def set_identifier(self, name): self.name = name; return self
            def set_address(self, *_): return self
            def set_drop_zone(self, *_): return self
            def set_packet(self, *_): return self
            def receive(self):
                with os.fdopen(os.open(self.name, os.O_RDONLY, dir_fd=self.fd), "r") as file:
                    data = json.load(file)
                return SimpleNamespace(get_packet=lambda: data)
            def close(self): os.close(self.fd)
        self.agent.get_reception_agent = lambda *args, **kwargs: Receiver()
        self.agent.get_delivery_packet = lambda *args, **kwargs: object()
        path = {"path": self.agent.path_resolution["comm_path"], "address": "agent", "drop": "directive", "name": "agent_tree.json"}
        with patch("core.python_core.boot_agent.ENCRYPTION_CONFIG.is_enabled", return_value=False):
            parsed = self.agent.load_directive(path, object())
        self.assertEqual(parsed.root["universal_id"], "agent")

    def test_ready_marker_binds_current_process_and_source(self):
        with runtime_directory(str(self.base), "u", "boot", "pod", child="pod1", create_child=True):
            pass
        self.agent.command_line_args["install_name"] = "pod1"
        self.agent._source_sha256 = "a" * 64
        self.agent.running = True
        self.agent._publish_ready_marker()
        marker = json.loads((self.base / "universes/runtime/u/boot/pod/pod1/ready.json").read_text())
        self.assertEqual(marker["pid"], os.getpid())
        self.assertEqual(marker["universal_id"], "agent")
        self.assertEqual(marker["source_sha256"], "a" * 64)
        self.assertGreater(marker["process_started_at"], 0)

    def test_ready_marker_refuses_unverified_source_and_link(self):
        with runtime_directory(str(self.base), "u", "boot", "pod", child="pod1", create_child=True):
            pass
        self.agent.command_line_args["install_name"] = "pod1"
        self.agent.running = True
        self.agent._source_sha256 = None
        with self.assertRaises(ValueError):
            self.agent._publish_ready_marker()
        self.agent._source_sha256 = "a" * 64
        outside = self.base / "outside"
        outside.write_text("keep")
        (self.base / "universes/runtime/u/boot/pod/pod1/ready.json").symlink_to(outside)
        with self.assertRaises(ValueError):
            self.agent._publish_ready_marker()
        self.assertEqual(outside.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
