"""Exercise Harvester's real worker/policy with isolated transport and boot."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from copy import deepcopy
import fnmatch
import json
import time
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import Mock
import uuid

from tests.test_harvester_policy import AGENT_PATH, CHECK, POLICY, ROOT, target


def load_agent(clock, sleep):
    """Load the agent and role lookup without starting BootAgent or SSH."""
    boot_path = ROOT / "matrixos/core/python_core/boot_agent.py"
    endpoint_path = (
        ROOT / "matrixos/core/python_core/class_lib/service/service_endpoint.py"
    )
    boot_tree = ast.parse(boot_path.read_text(encoding="utf-8"))
    boot_class = next(node for node in boot_tree.body if isinstance(node, ast.ClassDef))
    role_lookup = next(
        node for node in boot_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_nodes_by_role"
    )
    boot_stub = ast.ClassDef(
        name="BootAgent", bases=[], keywords=[], body=[role_lookup], decorator_list=[]
    )
    agent_tree = ast.parse(AGENT_PATH.read_text(encoding="utf-8"))
    agent_class = next(node for node in agent_tree.body if isinstance(node, ast.ClassDef))
    namespace = {
        "Any": Any, "Mapping": Mapping, "fnmatch": fnmatch, "time": clock,
        "interruptible_sleep": sleep,
        "SSHCheckRunner": CHECK.SSHCheckRunner,
        "SSHCheckError": CHECK.SSHCheckError,
        "SSHCheckCancelled": CHECK.SSHCheckCancelled,
        **{
            name: getattr(POLICY, name) for name in (
                "HarvesterPolicyError", "evaluate_observation", "initial_state",
                "normalize_target", "observation_for_target", "parse_matrixd_snapshot",
                "record_recovery_attempt", "recovery_due",
            )
        },
    }
    exec(compile(endpoint_path.read_text(encoding="utf-8"), str(endpoint_path), "exec"), namespace)
    module = ast.fix_missing_locations(ast.Module(body=[boot_stub, agent_class], type_ignores=[]))
    exec(compile(module, str(AGENT_PATH), "exec"), namespace)
    return namespace["Agent"]


def load_packets():
    """Use production packet implementations, including nested auto-fill."""
    packet_root = ROOT / "matrixos/core/python_core/class_lib/packet_delivery"
    namespace = {}
    base_path = packet_root / "interfaces/base_packet.py"
    exec(compile(base_path.read_text(encoding="utf-8"), str(base_path), "exec"), namespace)
    packet_types = {}
    for identifier in ("notify.alert.general", "standard.command.packet"):
        path = packet_root / "packet" / (identifier.replace(".", "/") + ".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        packet_class = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        scope = {"BasePacket": namespace["BasePacket"], "time": time, "uuid": uuid}
        exec(compile(ast.Module(body=[packet_class], type_ignores=[]), str(path), "exec"), scope)
        packet_types[identifier] = scope["Packet"]
    return packet_types


def load_plaintext_relay():
    """Exercise Telegram's real handler/formatter without network or boot."""
    path = ROOT / "matrixos/agents/python_core/telegram_relay/telegram_relay.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    agent_class = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    methods = [node for node in agent_class.body if isinstance(node, ast.FunctionDef)
               and node.name in {"cmd_send_alert_msg", "format_message"}]
    stub = ast.ClassDef(name="Relay", bases=[], keywords=[], body=methods, decorator_list=[])
    namespace = {"IdentityObject": object}
    module = ast.fix_missing_locations(ast.Module(body=[stub], type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    relay = namespace["Relay"]()
    relay.alerts_enabled = True
    relay.encrypt_alerts = False
    relay.send_to_telegram = Mock(return_value=True)
    relay.log = Mock()
    return relay


class HarvesterAlertDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.clock = SimpleNamespace(time=Mock(return_value=100.0), monotonic=Mock(return_value=0.0))
        self.sleep = Mock()
        agent_class = load_agent(self.clock, self.sleep)
        self.agent = agent_class.__new__(agent_class)
        self.target = target(confirm_healthy_once=True)
        self.agent.tree_node = {"config": {
            "enabled": True, "mode": "ssh", "ssh": {},
            "check_interval_sec": 30, "targets": [self.target],
        }}
        self.agent.command_line_args = {"universal_id": "harvester-test"}
        self.agent.running = True
        self.agent.log = Mock()
        self.agent.check_for_thread_poke = Mock(return_value=Mock())
        agent_class.__init__(self.agent)
        self.agent._matrixd_list = Mock(return_value=self.snapshot(healthy=True))
        self.catalog = []
        self.agent.get_cached_service_managers = lambda: self.catalog
        self.packet_types = load_packets()
        self.agent.get_delivery_packet = Mock(side_effect=self.packet_factory)
        self.agent.pass_packet = Mock(return_value=True)

    def packet_factory(self, identifier, **kwargs):
        return self.packet_types[identifier]()

    @staticmethod
    def snapshot(*, healthy):
        return json.dumps({"version": 1, "universes": [
            {"universe": "phoenix", "status": "active", "agent_count": 6}
        ] if healthy else []})

    def add_relay(self, uid="telegram-test"):
        self.catalog.append({"universal_id": uid, "config": {"service-manager": [{
            "role": ["comm", "comm.security", "comm.*", "hive.alert@cmd_send_alert_msg"],
            "scope": ["parent", "any"], "auth": {"sig": True},
        }]}})

    def cycle(self, *, healthy=True, now=None):
        if now is not None:
            self.clock.time.return_value = now
        self.agent._matrixd_list.return_value = self.snapshot(healthy=healthy)
        self.agent._run_cycle()

    def messages(self):
        return [call.args[0] for call in self.agent.log.call_args_list]

    def events(self):
        return [call.args[0].get_packet()["content"]["cause"]
                for call in self.agent.pass_packet.call_args_list]

    def test_worker_checks_before_sleep_and_logs_initial_result_only_once(self):
        self.add_relay()
        order = Mock()
        order.attach_mock(self.agent._matrixd_list, "check")
        order.attach_mock(self.agent._emit_beacon, "beacon")
        order.attach_mock(self.sleep, "sleep")
        self.agent.worker()
        self.agent.worker()
        self.assertEqual([call[0] for call in order.mock_calls],
                         ["beacon", "check", "beacon", "sleep"] * 2)
        self.assertEqual(self.events(), ["Harvester HEALTHY"])
        initial = [msg for msg in self.messages() if "Initial observation" in msg]
        self.assertEqual(len(initial), 1)
        self.assertIn("result=healthy status=ACTIVE_6_AGENTS", initial[0])
        self.assertFalse(self.agent._pending_alerts)

    def test_startup_confirmation_survives_delayed_service_discovery(self):
        self.cycle()
        self.assertEqual(self.agent._states[self.target["id"]]["status"], "up")
        self.assertEqual(self.agent._pending_alerts[self.target["id"]]["event"], "HEALTHY")
        self.agent.pass_packet.assert_not_called()
        self.cycle(now=130)
        self.add_relay()
        self.cycle(now=160)
        self.cycle(now=190)
        self.assertEqual(self.events(), ["Harvester HEALTHY"])
        packet, uid = self.agent.pass_packet.call_args.args
        wire = packet.get_packet()
        self.assertEqual(uid, "telegram-test")
        self.assertEqual(wire["handler"], "cmd_send_alert_msg")
        self.assertEqual(wire["content"]["observed_at"], 160)
        self.assertIn("monitoring established", wire["content"]["msg"])
        self.assertFalse(self.agent._pending_alerts)
        self.assertEqual(self.agent._matrixd_list.call_count, 4)

    def test_confirmation_disabled_still_logs_first_check_without_alert(self):
        self.agent.targets[0]["confirm_healthy_once"] = False
        self.add_relay()
        self.cycle()
        self.cycle()
        self.agent.pass_packet.assert_not_called()
        self.assertFalse(self.agent._pending_alerts)
        self.assertTrue(any("Initial observation" in msg for msg in self.messages()))

    def test_failed_dispatch_retries_without_claiming_success(self):
        self.add_relay()
        self.agent.pass_packet.side_effect = [False, True]
        self.cycle()
        self.assertTrue(self.agent._pending_alerts)
        self.assertFalse(any("Dispatched event=" in msg for msg in self.messages()))
        self.cycle()
        self.cycle()
        self.assertEqual(self.agent.pass_packet.call_count, 2)
        self.assertFalse(self.agent._pending_alerts)
        self.assertEqual(sum("Dispatched event=" in msg for msg in self.messages()), 1)

    def test_partial_fanout_retries_only_unsent_relay_even_on_exception(self):
        self.add_relay("a")
        self.add_relay("b")
        def dispatch(packet, uid):
            if uid == "a" and self.agent.pass_packet.call_count == 1:
                raise RuntimeError("sensitive exception detail")
            return True
        self.agent.pass_packet.side_effect = dispatch
        self.cycle()
        self.cycle()
        self.cycle()
        self.assertEqual([c.args[1] for c in self.agent.pass_packet.call_args_list], ["a", "b", "a"])
        self.assertNotIn("sensitive exception detail", " ".join(self.messages()))
        self.assertFalse(self.agent._pending_alerts)

    def test_duplicate_role_declarations_are_dispatched_once(self):
        self.add_relay()
        self.add_relay()
        self.cycle()
        self.agent.pass_packet.assert_called_once()

    def test_new_down_event_supersedes_queued_healthy_notice(self):
        self.cycle()
        self.add_relay()
        self.cycle(healthy=False)
        self.agent.pass_packet.assert_not_called()
        self.cycle(healthy=False)
        self.assertEqual(self.events(), ["Harvester DOWN"])
        self.cycle()
        self.cycle()
        self.assertEqual(self.events(), ["Harvester DOWN", "Harvester RECOVERY"])

    def test_recovered_target_never_dispatches_stale_down_notice(self):
        self.cycle(healthy=False)
        self.cycle(healthy=False)
        self.add_relay()
        self.cycle()
        self.agent.pass_packet.assert_not_called()
        self.cycle()
        self.assertEqual(self.events(), ["Harvester RECOVERY"])
        self.assertFalse(self.agent._pending_alerts)

    def test_transient_failure_defers_healthy_notice_until_next_success(self):
        self.cycle()
        self.add_relay()
        self.cycle(healthy=False)
        self.agent.pass_packet.assert_not_called()
        self.cycle()
        self.assertEqual(self.events(), ["Harvester HEALTHY"])

    def test_reminders_do_not_reset_pending_delivery_or_spam_successful_relay(self):
        self.add_relay("a")
        self.add_relay("b")
        self.agent.pass_packet.side_effect = lambda packet, uid: uid == "a"
        self.cycle(healthy=False, now=100)
        self.cycle(healthy=False, now=130)
        self.cycle(healthy=False, now=160)
        self.cycle(healthy=False, now=190)
        self.assertEqual([c.args[1] for c in self.agent.pass_packet.call_args_list], ["a", "b", "b", "b"])
        self.assertEqual(set(self.events()), {"Harvester DOWN"})
        self.agent.pass_packet.side_effect = None
        self.cycle(healthy=False, now=220)
        self.assertFalse(self.agent._pending_alerts)
        self.assertEqual(self.agent._states[self.target["id"]]["last_alert_at"], 220)
        self.cycle(healthy=False, now=249)
        self.assertEqual(self.agent.pass_packet.call_count, 5)
        self.cycle(healthy=False, now=250)
        self.assertEqual(self.events()[-2:], ["Harvester DOWN_REMINDER"] * 2)

    def test_pending_warnings_are_rate_limited_but_checks_continue(self):
        for elapsed in (0, 10, 30, 59, 60):
            self.clock.monotonic.return_value = elapsed
            self.cycle()
        pending_logs = [msg for msg in self.messages() if "[ALERT] Pending" in msg]
        self.assertEqual(len(pending_logs), 2)
        self.assertTrue(all("will retry" in msg for msg in pending_logs))
        self.assertEqual(self.agent._matrixd_list.call_count, 5)

    def test_failed_collection_logs_initial_failure_and_keeps_threshold(self):
        self.add_relay()
        self.agent._matrixd_list.side_effect = RuntimeError("secret transport details")
        self.cycle()
        self.agent.pass_packet.assert_not_called()
        self.cycle()
        self.assertEqual(self.events(), ["Harvester DOWN"])
        self.assertTrue(any("result=unhealthy status=RuntimeError" in msg for msg in self.messages()))
        self.assertNotIn("secret transport details", " ".join(self.messages()))

    def test_pending_storage_is_bounded_across_long_alert_outage(self):
        for index in range(30):
            self.cycle(healthy=(index % 4 < 2), now=100 + index * 30)
            self.assertLessEqual(len(self.agent._pending_alerts), 1)
        self.agent.pass_packet.assert_not_called()
        self.assertEqual(self.agent._matrixd_list.call_count, 30)

    def test_packet_construction_failure_retains_notification(self):
        self.add_relay()
        self.agent.get_delivery_packet.side_effect = RuntimeError("packet factory failed")
        self.cycle()
        self.assertTrue(self.agent._pending_alerts)
        self.agent.get_delivery_packet.side_effect = self.packet_factory
        self.cycle()
        self.assertEqual(self.events(), ["Harvester HEALTHY"])

    def test_real_command_serialization_is_initialized_stable_and_valid(self):
        self.add_relay()
        self.cycle()
        packet = self.agent.pass_packet.call_args.args[0]
        first = deepcopy(packet.get_packet())
        second = json.loads(json.dumps(packet.get_packet()))
        self.assertEqual(first, second)
        self.assertTrue(packet.is_valid())
        self.assertTrue(packet._packet.is_valid())
        self.assertEqual(packet._packet.get_error_success(), 0)
        self.assertEqual(second["handler"], "cmd_send_alert_msg")
        self.assertIn("nonce", second)
        self.assertIn("timestamp", second)
        self.assertEqual(second["content"]["universal_id"], "harvester-test")
        self.assertEqual(second["content"]["observed_at"], 100)
        self.assertIn("Harvester HEALTHY", second["content"]["formatted_msg"])

    def test_all_relays_receive_real_content_after_serialization_and_retry(self):
        relays = {uid: load_plaintext_relay() for uid in ("a", "b")}
        wires = []
        def dispatch(packet, uid):
            # File delivery reads the packet for validation and again for crypto.
            packet.get_packet()
            wire = json.loads(json.dumps(packet.get_packet()))
            wires.append(wire)
            relays[uid].cmd_send_alert_msg(wire.get("content", {}), wire)
            return True
        self.agent.pass_packet.side_effect = dispatch
        self.cycle()  # Catalog not yet delivered at startup.
        for uid in relays:
            self.add_relay(uid)
        self.cycle(now=130)
        self.cycle(now=160)  # No repeated startup confirmation.
        self.cycle(healthy=False, now=190)
        self.cycle(healthy=False, now=220)
        self.cycle(healthy=False, now=250)
        self.cycle(now=280)
        self.cycle(now=310)
        self.assertEqual(len(wires), 8)
        self.assertEqual(len({wire["nonce"] for wire in wires}), 8)
        for relay in relays.values():
            messages = [call.args[0] for call in relay.send_to_telegram.call_args_list]
            self.assertEqual(len(messages), 4)
            for message, event in zip(messages, ("HEALTHY", "DOWN", "DOWN_REMINDER", "RECOVERY")):
                self.assertIn(f"Harvester {event}:", message)
                self.assertIn("universe=phoenix", message)
                self.assertNotIn("[SWARM] No content.", message)
            self.assertIn("ACTIVE_6_AGENTS", messages[0])
            self.assertIn("monitoring established", messages[0])

    def test_disabled_agent_does_not_check_or_dispatch(self):
        self.agent.enabled = False
        self.agent.worker()
        self.agent._matrixd_list.assert_not_called()
        self.agent.pass_packet.assert_not_called()
        self.sleep.assert_called_once_with(self.agent, 30)

    def test_ssh_failures_obey_threshold_and_report_safe_reason(self):
        self.add_relay()
        self.agent._matrixd_list.side_effect = CHECK.SSHCheckError("SSH_AUTH_FAILED")
        self.cycle()
        self.agent.pass_packet.assert_not_called()
        self.cycle()
        self.assertEqual(self.events(), ["Harvester DOWN"])
        packet = self.agent.pass_packet.call_args.args[0].get_packet()
        self.assertIn("SSH_AUTH_FAILED", packet["content"]["msg"])
        self.assertNotIn("UNIVERSE_ABSENT", packet["content"]["msg"])

    def test_shutdown_cancellation_is_not_a_failed_observation(self):
        self.agent._matrixd_list.side_effect = CHECK.SSHCheckCancelled()
        self.cycle()
        self.assertEqual(self.agent._states[self.target["id"]]["failure_hits"], 0)
        self.agent.pass_packet.assert_not_called()

    def test_ssh_check_uses_supervisor_with_beacon_and_cancellation(self):
        checker = Mock()
        self.agent._ssh_checker = checker
        type(self.agent)._matrixd_list(self.agent)
        args, kwargs = checker.run.call_args
        self.assertEqual(args, ({}, 60))
        kwargs["pulse"]()
        self.agent._emit_beacon.assert_called_once()
        self.assertFalse(kwargs["cancelled"]())
        self.agent.running = False
        self.assertTrue(kwargs["cancelled"]())
        self.agent.worker_post()
        checker.close.assert_called_once()

    def test_beacon_budget_covers_long_check_and_short_poll_interval(self):
        self.agent.tree_node["config"].update(check_interval_sec=5, matrixd_timeout_sec=300)
        type(self.agent).__init__(self.agent)
        beacon_timeout = self.agent.check_for_thread_poke.call_args.kwargs["timeout"]
        self.assertGreater(beacon_timeout, 300 + 5)


if __name__ == "__main__":
    unittest.main()
