"""Exercise Phoenix reminder CRUD and verified callback correlation."""
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
except ImportError:
    QApplication = None

class Bus:
    def __init__(self): self.listeners, self.sent = {}, []
    def on(self, name, handler): self.listeners.setdefault(name, []).append(handler)
    def off(self, name, handler): self.listeners[name].remove(handler)
    def emit(self, name, **kwargs): self.sent.append(kwargs["packet"].get_packet())

@unittest.skipIf(QApplication is None, "Phoenix GUI dependencies not installed")
class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from matrix_gui.core.panel.custom_panels.global_alarm.global_alarm import GlobalAlarm
        cls.Panel = GlobalAlarm
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.bus = Bus()
        self.panel = self.Panel("session-a", self.bus, node={"universal_id": "global-a"})
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()

    def reply(self, **kwargs):
        content = dict(token=self.panel.token, agent_uid="global-a", ok=True,
                       request_id=self.panel.pending[0], revision=0, alarms=[], runtime={},
                       destinations=["email-a", "telegram-a"], default_alert_role="hive.alert")
        content.update(kwargs)
        self.panel._handle_reply("session-a", payload={"content": content})
        self.app.processEvents()

    def test_create_update_and_delete_saved_alarms(self):
        self.reply()
        self.panel.title_edit.setText("Birthday")
        self.panel.message_edit.setPlainText("Call Mom")
        self.panel.alert_role.setText("hive.alarm.telegram")
        self.panel.btn_save.click()
        request = self.bus.sent[-1]["content"]
        self.assertEqual(request["service"], "hive.global_alarm.update")
        item = request["payload"]["alarms"][0]
        self.assertEqual(item["alert_role"], "hive.alarm.telegram")
        self.assertEqual(item["message"], "Call Mom")
        self.reply(revision=1, alarms=[item])
        self.panel.table.selectRow(0)
        self.app.processEvents()
        self.panel.message_edit.setPlainText("Call Mom tonight")
        self.panel.btn_save.click()
        updated = self.bus.sent[-1]["content"]["payload"]["alarms"][0]
        self.assertEqual(updated["id"], item["id"])
        self.assertEqual(updated["message"], "Call Mom tonight")
        self.reply(revision=2, alarms=[updated])
        self.panel.table.selectRow(0)
        self.app.processEvents()
        self.panel.btn_delete.click()
        self.panel.btn_save.click()
        self.assertEqual(self.bus.sent[-1]["content"]["payload"]["alarms"], [])
        self.reply(revision=3)
        self.assertEqual(self.panel.table.rowCount(), 0)

    def test_bad_callback_and_rejection_preserve_draft(self):
        pending = self.panel.pending[0]
        self.panel._handle_reply("other", payload={"content": {"token": self.panel.token,
            "agent_uid": "global-a", "request_id": pending}})
        self.app.processEvents()
        self.assertEqual(self.panel.pending[0], pending)
        self.reply()
        self.panel.title_edit.setText("Reminder")
        self.panel.message_edit.setPlainText("Test")
        self.panel.alert_role.setText("hive.alert")
        self.panel.btn_save.click()
        self.reply(ok=False, error="Unknown time zone")
        self.assertEqual(self.panel.alarms[0]["message"], "Test")
        self.assertTrue(self.panel.dirty)
        self.assertIn("Unknown time zone", self.panel.status.text())
        self.panel.hide()
        self.app.processEvents()
        self.assertTrue(all(not listeners for listeners in self.bus.listeners.values()))

    def test_legacy_targets_are_preserved_until_explicitly_converted(self):
        legacy = {"id": "old", "title": "Old", "message": "Hello", "timezone": "UTC",
                  "start_local": "2026-11-03T10:00", "repeat": "once", "enabled": True,
                  "destinations": ["email-a"]}
        self.reply(alarms=[legacy])
        self.panel.table.selectRow(0)
        self.app.processEvents()
        self.panel.message_edit.setPlainText("Edited")
        self.panel.btn_save.click()
        saved = self.bus.sent[-1]["content"]["payload"]["alarms"][0]
        self.assertEqual(saved["destinations"], ["email-a"])
        self.assertNotIn("alert_role", saved)
        self.reply(revision=1, alarms=[saved])
        self.panel.table.selectRow(0)
        self.app.processEvents()
        self.panel.use_role.setChecked(True)
        self.panel.alert_role.setText("hive.new")
        self.panel.btn_save.click()
        converted = self.bus.sent[-1]["content"]["payload"]["alarms"][0]
        self.assertEqual(converted["alert_role"], "hive.new")
        self.assertNotIn("destinations", converted)

    def test_server_clock_and_live_runtime_do_not_overwrite_draft(self):
        alarm = {"id": "one", "title": "Test", "message": "original", "timezone": "UTC",
                 "start_local": "2026-11-03T10:00", "repeat": "once", "enabled": True,
                 "alert_role": "hive.alert"}
        self.reply(alarms=[alarm], server_clock={"local_time": "2026-11-03T06:32:00+00:00",
                                                "timezone": "Etc/UTC", "abbreviation": "UTC"})
        self.assertIn("Etc/UTC", self.panel.clock_label.text())
        self.panel.table.selectRow(0)
        self.app.processEvents()
        self.panel.message_edit.setPlainText("unsaved edit")
        self.panel._request_clock()
        pending_id = self.panel._clock_pending[0]
        self.panel._handle_clock("session-a", payload={"content": {
            "token": self.panel.token, "agent_uid": "global-a", "request_id": pending_id,
            "ok": True, "revision": 0,
            "server_clock": {"local_time": "2026-11-03T06:32:05+00:00", "timezone": "UTC"},
            "runtime": {"one": {"pending": {"occurrence": "2026-11-03T06:32:00+00:00", "queued": []}}}}})
        self.app.processEvents()
        self.assertEqual(self.panel.message_edit.toPlainText(), "unsaved edit")
        self.assertTrue(self.panel.form_dirty)
        self.assertEqual(self.panel.table.item(0, 3).text(), "Unsaved edit")
        self.assertIn("pending", self.panel.runtime["one"])
        self.assertIn("06:32:05", self.panel.clock_label.text())
        self.panel._render_clock(time.monotonic() + 60)
        self.assertIn("stale", self.panel.clock_label.text())

    def test_new_draft_is_not_mislabeled_scheduled(self):
        self.reply()
        self.panel.title_edit.setText("Draft")
        self.panel.message_edit.setPlainText("Not saved")
        self.panel._apply()
        self.assertEqual(self.panel.table.item(0, 3).text(), "Unsaved")

if __name__ == "__main__": unittest.main()
