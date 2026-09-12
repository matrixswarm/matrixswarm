"""Real Qt panel tests when the optional Phoenix GUI dependencies are installed."""
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
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
        from matrix_gui.core.panel.custom_panels.crypto_alert.crypto_alert import CryptoAlert
        cls.Panel = CryptoAlert
        cls.app = QApplication.instance() or QApplication([])
        if os.name == "nt":
            from PyQt6.QtGui import QFont, QFontDatabase
            # The offscreen platform does not discover Windows fonts reliably.
            font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "consola.ttf"
            if font_path.is_file():
                QFontDatabase.addApplicationFont(str(font_path))
                cls.app.setFont(QFont("Consolas", 10))

    def setUp(self):
        self.bus = Bus()
        self.panel = self.Panel("session-a", self.bus, node={"universal_id": "crypto-a"})
        self.panel.resize(1200, 920)
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()

    def reply(self, **kwargs):
        content = dict(token=self.panel.token, agent_uid="crypto-a", ok=True,
                       request_id=self.panel.pending[0], revision=0, watch_list=[],
                       live={}, runtime={}, feed_status="live")
        content.update(kwargs)
        self.panel._handle_config_update("session-a", payload={"content": content})
        self.app.processEvents()

    def test_load_add_edit_save_ack_and_delete_all(self):
        self.reply()
        self.panel.btn_add.click()
        card = self.panel.alert_cards[0]
        self.assertEqual(card.threshold_edit.text(), "")
        card.pair_edit.setText("BTC/ETH")
        card._update_field_visibility()
        self.assertEqual(card.threshold_label.text(), "Alert ratio (ETH per BTC):")
        card.threshold_edit.setText("20")
        self.panel.btn_save.click()
        request = self.bus.sent[-1]
        self.assertEqual(request["handler"], "cmd_service_request")
        self.assertEqual(request["content"]["service"], "hive.crypto_alert.update_config")
        payload = request["content"]["payload"]
        self.assertEqual(payload["target_universal_id"], "crypto-a")
        self.assertTrue(self.panel.dirty)
        self.assertFalse(self.panel.btn_save.isEnabled())
        self.reply(revision=1, watch_list=payload["watch_list"])
        self.assertFalse(self.panel.dirty)
        self.panel.alert_cards[0].delete_btn.click()
        self.panel.btn_save.click()
        self.assertEqual(self.bus.sent[-1]["content"]["payload"]["watch_list"], [])
        self.reply(revision=2)
        self.assertEqual(self.panel.card_layout.count(), 0)

    def test_callbacks_are_scoped_and_timeout_preserves_draft(self):
        original = self.panel.pending
        self.reply(agent_uid="other")
        self.reply(token="other")
        self.reply(request_id="other")
        self.assertEqual(self.panel.pending, original)
        self.reply()
        self.panel._add_card()
        self.panel.alert_cards[0].threshold_edit.setText("78000")
        self.panel.alert_cards[0].threshold_edit.textEdited.emit("78000")
        self.panel._push_config()
        self.panel.pending = (*self.panel.pending[:2], time.monotonic()-21)
        self.panel._tick()
        self.assertEqual(len(self.panel.alert_cards), 1)
        self.assertTrue(self.panel.dirty)
        self.assertIn("No acknowledgment", self.panel.status_label.text())

    def test_stream_does_not_overwrite_edits_and_hide_releases_subscription(self):
        self.reply(watch_list=[{"id": "a", "pair": "BTC/ETH", "threshold": 20}])
        self.panel.alert_cards[0].threshold_edit.setText("25")
        self.panel.alert_cards[0].threshold_edit.textEdited.emit("25")
        self.panel._handle_price_update("session-a", payload={"content": {
            "token": self.panel.token, "agent_uid": "crypto-a", "revision": 0,
            "live": {"a": {"price": 20, "price_ts": time.time(), "derived": True}}, "runtime": {}}})
        self.app.processEvents()
        self.assertEqual(self.panel.alert_cards[0].threshold_edit.text(), "25")
        self.assertIn("Unsaved draft", self.panel.alert_cards[0].boiler_label.text())
        self.assertTrue(self.panel.alert_cards[0]._live["derived"])
        self.panel.hide()
        self.app.processEvents()
        self.assertEqual(self.bus.sent[-1]["content"]["service"], "hive.crypto_alert.stop_stream")
        self.assertTrue(all(not listeners for listeners in self.bus.listeners.values()))
        self.assertFalse(self.panel.renew_timer.isActive())
        self.panel.show()
        self.app.processEvents()
        self.assertTrue(all(len(listeners) == 1 for listeners in self.bus.listeners.values()))

    def test_invalid_conversion_stays_editable_and_save_ack_preserves_newer_typing(self):
        self.reply(watch_list=[{"id": "convert", "trigger_type": "asset_conversion",
                                "from_asset": "ETH", "to_asset": "BTC",
                                "from_amount": .034, "threshold": 1}])
        card = self.panel.alert_cards[0]
        self.assertEqual(card.header_label.text(), "ETH/BTC · asset_conversion")
        self.assertEqual(card.from_amount_label.text(), "Amount of ETH:")
        self.assertEqual(card.threshold_label.text(), "Alert when conversion reaches (BTC):")
        card.threshold_edit.clear()
        card.threshold_edit.textEdited.emit("")
        sent_before = len(self.bus.sent)
        self.panel.btn_save.click()
        self.assertEqual(len(self.bus.sent), sent_before)
        self.assertIn("Conversion target is required", self.panel.status_label.text())
        self.assertTrue(card.threshold_edit.isEnabled())

        card.threshold_edit.setText("0.001")
        card.threshold_edit.textEdited.emit("0.001")
        self.panel.btn_save.click()
        submitted = self.bus.sent[-1]["content"]["payload"]["watch_list"]
        self.assertTrue(card.from_amount_edit.isEnabled())
        card.from_amount_edit.setText("0.035")
        card.from_amount_edit.textEdited.emit("0.035")
        self.reply(revision=1, watch_list=submitted)
        self.assertEqual(self.panel.alert_cards[0].from_amount_edit.text(), "0.035")
        self.assertTrue(self.panel.dirty)
        self.assertIn("newer edits remain unsaved", self.panel.status_label.text())

    def test_cards_wallet_conversion_and_optional_screenshot(self):
        self.reply(watch_list=[
            {"id": "price", "pair": "BTC/ETH", "trigger_type": "price_change_above", "change_percent": 5},
            {"id": "wallet", "trigger_type": "wallet_change", "address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"},
            {"id": "convert", "trigger_type": "asset_conversion", "from_amount": .1, "threshold": 2},
        ])
        self.app.processEvents()
        self.assertTrue(self.panel.alert_cards[1].wallet_wrap.isVisible())
        self.assertTrue(self.panel.alert_cards[2].conv_wrap.isVisible())
        for card in self.panel.alert_cards:
            self.assertGreaterEqual(card.width(), 350)
            self.assertGreater(card.height(), 350)
        if os.environ.get("CRYPTO_UI_SCREENSHOT"):
            self.assertTrue(self.panel.grab().save(os.environ["CRYPTO_UI_SCREENSHOT"]))


if __name__ == "__main__":
    unittest.main()
