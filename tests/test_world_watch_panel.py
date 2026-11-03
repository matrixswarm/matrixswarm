"""Focused watch panel routing, saving and snapshot retrieval."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'phoenix'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from matrix_gui.core.panel.custom_panels.promise_keeper.promise_keeper import PromiseKeeper
from matrix_gui.core.panel.custom_panels.change_of_fortune.change_of_fortune import ChangeOfFortune

class Bus:
    def __init__(self): self.listeners, self.sent = {}, []
    def on(self, name, cb): self.listeners.setdefault(name, []).append(cb)
    def off(self, name, cb): self.listeners[name].remove(cb)
    def emit(self, name, **kwargs): self.sent.append(kwargs['packet'].get_packet())

class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_agent_panel_save_and_snapshot_chunks(self):
        for panel_class, prefix in ((PromiseKeeper, 'hive.promise_keeper.'), (ChangeOfFortune, 'hive.change_of_fortune.')):
            with self.subTest(panel=panel_class):
                bus = Bus(); panel = panel_class('session', bus, node={'universal_id': 'agent'})
                panel.show(); self.app.processEvents()
                def reply(**values):
                    data = {'token': panel.token, 'agent_uid': 'agent', 'ok': True,
                        'request_id': panel.pending[0], 'revision': 0, 'sources': [], 'blocked_hosts': {},
                        'observations': {}, 'events': [], 'captures': []}
                    data.update(values)
                    panel._handle_reply('session', payload={'content': data}); self.app.processEvents()
                reply()
                panel.name.setText('Watch'); panel.url.setText('https://example.com/')
                panel.keywords.setPlainText('release'); panel.save_button.click()
                self.assertEqual(bus.sent[-1]['content']['service'], prefix + 'update')
                source = bus.sent[-1]['content']['payload']['sources'][0]
                capture = {'id': 'capture', 'source_id': source['id'], 'captured_at': 1000, 'sha256': 'hash'}
                reply(revision=1, sources=[source], captures=[capture])
                self.assertEqual(panel.capture_select.count(), 1)
                panel.view_capture.click()
                self.assertEqual(bus.sent[-1]['content']['service'], prefix + 'capture')
                reply(capture_id='capture', offset=0, next_offset=3, chunk='old', done=False)
                self.assertEqual(bus.sent[-1]['content']['payload']['offset'], 3)
                with patch.object(QDialog, 'exec', return_value=0):
                    reply(capture_id='capture', offset=3, next_offset=6, chunk='new', done=True, url=source['url'], sha256='hash')
                self.assertEqual(''.join(panel._capture_parts), 'oldnew')
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                    panel.clear_captures.click()
                self.assertEqual(bus.sent[-1]['content']['service'], prefix + 'clear_history')
                self.assertEqual(bus.sent[-1]['content']['payload']['source_id'], source['id'])
                panel.close(); panel.deleteLater(); self.app.processEvents()

if __name__ == '__main__': unittest.main()
