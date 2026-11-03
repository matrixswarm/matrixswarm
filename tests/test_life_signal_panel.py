"""LifeSignal panel source CRUD and callback correlation."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'phoenix'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
from matrix_gui.core.panel.custom_panels.life_signal.life_signal import LifeSignal


class Bus:
    def __init__(self): self.listeners, self.sent = {}, []
    def on(self, name, callback): self.listeners.setdefault(name, []).append(callback)
    def off(self, name, callback): self.listeners[name].remove(callback)
    def emit(self, name, **kwargs): self.sent.append(kwargs['packet'].get_packet())


class LifeSignalPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.bus = Bus()
        self.panel = LifeSignal('session', self.bus, node={'universal_id': 'life-a'})
        self.panel.show(); self.app.processEvents()

    def tearDown(self):
        self.panel.close(); self.panel.deleteLater(); self.app.processEvents()

    def reply(self, **changes):
        data = {'token': self.panel.token, 'agent_uid': 'life-a', 'ok': True,
                'request_id': self.panel.pending[0], 'revision': 0, 'sources': [],
                'blocked_hosts': {}, 'observations': {}, 'events': []}
        data.update(changes)
        self.panel._handle_reply('session', payload={'content': data})
        self.app.processEvents()

    def test_source_crud_and_saved_acknowledgment(self):
        self.reply()
        self.panel.name.setText('News')
        self.panel.url.setText('https://example.com/feed')
        self.panel.keywords.setPlainText('Jane Example\nretirement')
        self.panel.save_button.click()
        request = self.bus.sent[-1]['content']
        self.assertEqual(request['service'], 'hive.life_signal.update')
        source = request['payload']['sources'][0]
        self.assertEqual(source['keywords'], ['Jane Example', 'retirement'])
        self.reply(revision=1, sources=[source])
        self.panel.table.selectRow(0); self.app.processEvents()
        self.panel.delete_button.click(); self.panel.save_button.click()
        self.assertEqual(self.bus.sent[-1]['content']['payload']['sources'], [])

    def test_rejected_save_keeps_draft(self):
        self.reply()
        self.panel.name.setText('News'); self.panel.url.setText('https://example.com/')
        self.panel.keywords.setPlainText('Jane'); self.panel.save_button.click()
        self.reply(ok=False, error='Conflict')
        self.assertEqual(len(self.panel.sources), 1)
        self.assertTrue(self.panel.dirty)
        self.assertIn('Conflict', self.panel.status.text())

    def test_typing_two_minutes_saves_and_reloads_that_value(self):
        self.reply()
        self.panel.name.setText('News'); self.panel.url.setText('https://example.com/')
        self.panel.keywords.setPlainText('Jane')
        self.panel.interval.setFocus()
        self.panel.interval.lineEdit().selectAll()
        QTest.keyClicks(self.panel.interval.lineEdit(), '120')
        QTest.keyClick(self.panel.interval.lineEdit(), Qt.Key.Key_Tab)
        self.panel.save_button.click()
        source = self.bus.sent[-1]['content']['payload']['sources'][0]
        self.assertEqual(source['interval_sec'], 120)
        self.reply(revision=1, sources=[source])
        self.panel.table.selectRow(0); self.app.processEvents()
        self.assertEqual(self.panel.interval.value(), 120)

    def test_source_status_distinguishes_waiting_checked_and_pending(self):
        source = {'id': 'one', 'name': 'News', 'url': 'https://example.com/',
                  'kind': 'page', 'keywords': ['Jane'], 'interval_sec': 120,
                  'alert_role': 'hive.alert', 'enabled': True}
        self.reply(sources=[source])
        self.assertIn('Waiting for first successful check', self.panel.table.item(0, 2).text())
        self.panel.reload_button.click()
        self.reply(sources=[source], observations={'one': {'baseline_ready': True, 'last_success_at': 1000}},
                   pending_counts={'one': 1})
        status = self.panel.table.item(0, 2).text()
        self.assertIn('Checked', status)
        self.assertIn('1 awaiting Oracle', status)
        self.assertEqual(self.panel.table.item(0, 2).toolTip(), status)

    def test_captcha_monitor_can_be_saved_without_keywords(self):
        self.reply()
        self.panel.name.setText('Site challenge test')
        self.panel.url.setText('https://example.com/')
        self.panel.mode.setCurrentIndex(self.panel.mode.findData('captcha'))
        self.panel.save_button.click()
        source = self.bus.sent[-1]['content']['payload']['sources'][0]
        self.assertEqual(source['analysis_mode'], 'captcha')
        self.assertEqual(source['keywords'], [])


if __name__ == '__main__': unittest.main()
