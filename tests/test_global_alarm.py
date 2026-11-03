"""Scheduling, persistence, relay selection, and agent protocol tests."""
from copy import deepcopy
from datetime import datetime, timezone
import ast
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
sys.path.insert(0, str(ROOT / "matrixos" / "agents" / "python_core"))
from global_alarm.engine import AlarmEngine, normalize_alarm
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from core.python_core.class_lib.packet_delivery.packet.standard.command.packet import Packet as Command
from core.python_core.class_lib.packet_delivery.packet.notify.alert.general import Packet as Notice

UTC = timezone.utc

def alarm(**values):
    item = {"id": "alarm-one", "title": "Test", "message": "Time to go", "start_local": "2026-11-02T09:00",
            "timezone": "America/New_York", "repeat": "once", "enabled": True,
            "destinations": ["telegram-a", "email-a"]}
    item.update(values)
    return item

def moment(value):
    return datetime.fromisoformat(value).replace(tzinfo=UTC)

class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.saved = []
        self.notify = Mock(return_value=True)
        self.engine = AlarmEngine(lambda value: self.saved.append(deepcopy(value)), self.notify)
        self.engine.replace([alarm()], 0)

    def test_once_sends_only_selected_destinations_and_stays_done_after_restart(self):
        self.engine.tick(moment("2026-11-02T13:59:00"))
        self.assertEqual(self.notify.call_count, 0)
        self.engine.tick(moment("2026-11-02T14:00:00"))
        self.assertEqual([c.args[1] for c in self.notify.call_args_list], ["telegram-a", "email-a"])
        resumed = AlarmEngine(lambda value: self.saved.append(deepcopy(value)), self.notify, self.saved[-1])
        resumed.tick(moment("2026-11-02T15:00:00"))
        self.assertEqual(self.notify.call_count, 2)
        self.assertEqual(resumed.snapshot()["runtime"]["alarm-one"]["last_queued"], "2026-11-02T14:00:00+00:00")

    def test_failed_destination_retries_without_repeating_successful_one(self):
        self.notify.side_effect = [True, False, True]
        self.engine.tick(moment("2026-11-02T14:00:00"))
        self.assertEqual(self.engine.snapshot()["runtime"]["alarm-one"]["pending"]["queued"], ["telegram-a"])
        resumed = AlarmEngine(lambda value: self.saved.append(deepcopy(value)), self.notify, self.saved[-1])
        resumed.tick(moment("2026-11-02T14:01:00"))
        self.assertEqual([c.args[1] for c in self.notify.call_args_list], ["telegram-a", "email-a", "email-a"])
        self.assertNotIn("pending", resumed.snapshot()["runtime"]["alarm-one"])

    def test_daily_retains_local_hour_across_daylight_saving_and_coalesces_downtime(self):
        self.engine.replace([alarm(start_local="2026-10-31T09:00", repeat="daily")], 1)
        self.engine.tick(moment("2026-10-31T13:00:00"))
        self.assertEqual(self.engine.snapshot()["runtime"]["alarm-one"]["next_at"], "2026-11-01T14:00:00+00:00")
        self.engine.tick(moment("2026-11-04T15:00:00"))
        self.assertEqual(self.notify.call_count, 4)
        self.assertEqual(self.engine.snapshot()["runtime"]["alarm-one"]["next_at"], "2026-11-05T14:00:00+00:00")

    def test_edit_does_not_lose_pending_reminder(self):
        self.notify.side_effect = [True, False, True]
        self.engine.tick(moment("2026-11-02T14:00:00"))
        self.engine.replace([alarm(message="Updated message")], 1)
        self.engine.tick(moment("2026-11-02T14:01:00"))
        self.assertEqual([c.args[1] for c in self.notify.call_args_list], ["telegram-a", "email-a", "email-a"])
        self.assertEqual(self.notify.call_args.args[0]["message"], "Updated message")

    def test_gap_skipped_and_invalid_start_rejected(self):
        with self.assertRaises(ValueError):
            normalize_alarm(alarm(start_local="2026-03-08T02:30"))
        self.engine.replace([alarm(start_local="2026-03-07T02:30", repeat="daily")], 1)
        self.engine.tick(moment("2026-03-07T07:30:00"))
        self.assertEqual(self.engine.snapshot()["runtime"]["alarm-one"]["next_at"], "2026-03-09T06:30:00+00:00")

    def test_revision_conflict_and_failed_save_leave_state_unchanged(self):
        with self.assertRaises(ValueError):
            self.engine.replace([], 0)
        before = self.engine.snapshot()
        self.engine.persist = Mock(side_effect=OSError("disk full"))
        with self.assertRaises(OSError):
            self.engine.replace([], 1)
        self.assertEqual(self.engine.snapshot(), before)

    def test_message_edit_does_not_rearm_completed_alarm(self):
        self.engine.tick(moment("2026-11-02T14:00:00"))
        self.engine.replace([alarm(message="Edited")], 1)
        self.engine.tick(moment("2026-11-02T15:00:00"))
        self.assertEqual(self.notify.call_count, 2)

    def test_disabled_and_reenabled_due_alarm(self):
        self.engine.replace([alarm(enabled=False)], 1)
        self.engine.tick(moment("2026-11-02T14:00:00"))
        self.assertEqual(self.notify.call_count, 0)
        self.engine.replace([alarm()], 2)
        self.engine.tick(moment("2026-11-02T14:01:00"))
        self.assertEqual(self.notify.call_count, 2)

    def test_service_role_resolves_at_due_time_and_retries_without_listener(self):
        resolver = Mock(side_effect=[[], ["email-new", "telegram-new"]])
        engine = AlarmEngine(lambda value: self.saved.append(deepcopy(value)), self.notify,
                             resolve_destinations=resolver)
        item = alarm(alert_role="hive.special")
        item.pop("destinations")
        engine.replace([item], 0)
        engine.tick(moment("2026-11-02T14:00:00"))
        self.assertEqual(self.notify.call_count, 0)
        self.assertIn("pending", engine.snapshot()["runtime"]["alarm-one"])
        engine.tick(moment("2026-11-02T14:01:00"))
        self.assertEqual([call.args[1] for call in self.notify.call_args_list],
                         ["email-new", "telegram-new"])
        self.assertEqual(resolver.call_args.args[0]["alert_role"], "hive.special")

    def test_service_role_targets_are_frozen_after_partial_delivery_and_restart(self):
        resolver = Mock(return_value=["email-a", "telegram-a"])
        self.notify.side_effect = [True, False, True]
        engine = AlarmEngine(lambda value: self.saved.append(deepcopy(value)), self.notify,
                             resolve_destinations=resolver)
        item = alarm(alert_role="hive.alert")
        item.pop("destinations")
        engine.replace([item], 0)
        engine.tick(moment("2026-11-02T14:00:00"))
        resolver.reset_mock()
        resumed = AlarmEngine(lambda value: self.saved.append(deepcopy(value)), self.notify,
                              saved=self.saved[-1], resolve_destinations=resolver)
        resumed.tick(moment("2026-11-02T14:01:00"))
        resolver.assert_not_called()
        self.assertEqual([call.args[1] for call in self.notify.call_args_list],
                         ["email-a", "telegram-a", "telegram-a"])

    def test_pending_legacy_alarm_can_be_migrated_to_a_role(self):
        self.notify.side_effect = [True, False, True]
        self.engine.tick(moment("2026-11-02T14:00:00"))
        self.engine.resolve_destinations = Mock(return_value=["telegram-a", "new-relay"])
        updated = alarm(alert_role="hive.new")
        updated.pop("destinations")
        self.engine.replace([updated], 1)
        self.engine.tick(moment("2026-11-02T14:01:00"))
        self.assertEqual([call.args[1] for call in self.notify.call_args_list],
                         ["telegram-a", "email-a", "new-relay"])
        self.assertNotIn("pending", self.engine.snapshot()["runtime"]["alarm-one"])

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "matrixos/agents/python_core/global_alarm/global_alarm.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Agent")
        cls.bases = []
        ns = {"IdentityObject": IdentityObject, "re": re, "os": os}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), "exec"), ns)
        self.agent = ns["Agent"].__new__(ns["Agent"])
        self.agent.command_line_args = {"universal_id": "global-one"}
        self.agent.get_matrix_universal_id = lambda: "matrix"
        self.agent._rpc_role = "hive.rpc"
        self.agent._alert_role = "hive.alert"
        self.agent.log = Mock()
        self.agent.engine = AlarmEngine(lambda x: None, Mock())
        self.agent.crypto_reply = Mock()
        self.agent.get_nodes_by_role = Mock(return_value=[])
        self.content = {"target_universal_id": "global-one", "session_id": "session-a", "token": "token-a", "request_id": "request-a", "alarms": [], "revision": 0}

    def test_requires_exact_target_and_verified_matrix(self):
        for ident in (None, IdentityObject(False, "matrix"), IdentityObject(True, "other")):
            self.agent.cmd_update_alarms(self.content, None, ident)
        self.agent.cmd_update_alarms(dict(self.content, target_universal_id="other"), None, IdentityObject(True, "matrix"))
        self.agent.crypto_reply.assert_not_called()
        self.agent.cmd_update_alarms(self.content, None, IdentityObject(True, "matrix"))
        self.assertTrue(self.agent.crypto_reply.call_args.kwargs["payload"]["ok"])

    def test_clock_request_is_authenticated_and_does_not_return_alarm_messages(self):
        request = dict(self.content, clock_only=True)
        self.agent.cmd_get_alarms(request, None, IdentityObject(True, "other"))
        self.agent.crypto_reply.assert_not_called()
        self.agent.cmd_get_alarms(request, None, IdentityObject(True, "matrix"))
        result = self.agent.crypto_reply.call_args.kwargs
        self.assertEqual(result["response_handler"], "global_alarm.clock")
        self.assertIn("local_time", result["payload"]["server_clock"])
        self.assertEqual(result["payload"]["runtime"], {})
        self.assertNotIn("alarms", result["payload"])

    def test_selected_relay_receives_title_and_message(self):
        endpoint = Mock()
        endpoint.get_universal_id.return_value = "telegram-a"
        endpoint.get_handler.return_value = "cmd_send_alert_msg"
        self.agent.get_nodes_by_role.return_value = [endpoint]
        self.agent.get_delivery_packet = lambda name: Notice() if name == "notify.alert.general" else Command()
        self.agent.pass_packet = Mock(return_value=True)
        self.assertTrue(self.agent._queue_alert(alarm(), "telegram-a", "2026-11-02T14:00:00+00:00"))
        packet = self.agent.pass_packet.call_args.args[0].get_packet()
        self.assertIn("Test", packet["content"]["msg"])
        self.assertIn("Time to go", packet["content"]["msg"])
        self.assertFalse(self.agent._queue_alert(alarm(), "other", "2026-11-02T14:00:00+00:00"))

    def test_per_alarm_role_is_used_for_discovery_and_delivery(self):
        endpoint = Mock()
        endpoint.get_universal_id.return_value = "relay"
        endpoint.get_handler.return_value = "cmd_send_alert_msg"
        self.agent.get_nodes_by_role.return_value = [endpoint]
        self.agent.get_delivery_packet = lambda name: Notice() if name == "notify.alert.general" else Command()
        self.agent.pass_packet = Mock(return_value=True)
        item = alarm(alert_role="hive.special")
        self.assertEqual(self.agent._alarm_destinations(item), ["relay"])
        self.assertTrue(self.agent._queue_alert(item, "relay", "2026-11-02T14:00:00+00:00"))
        self.assertEqual(self.agent.get_nodes_by_role.call_args_list[0].args, ("hive.special",))
        self.assertEqual(self.agent.get_nodes_by_role.call_args_list[1].args, ("hive.special",))

if __name__ == "__main__":
    unittest.main()
