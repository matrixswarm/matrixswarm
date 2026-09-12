"""Offline crypto rules, feed protocol, persistence and worker regressions."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos" / "agents" / "python_core"))
sys.path.insert(0, str(ROOT / "matrixos"))
from crypto_alert.engine import AlertEngine, normalize_alert, evaluate_rule
from crypto_alert.market import PhemexFeed, parse_ticker, PHEMEX_URL
from crypto_alert.wallet import parse_address_stats, validate_address, validate_api_url, fetch_address
from core.python_core.mixin.encrypted_state import EncryptedStateMixin, EncryptedStateError

ADDRESS = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"  # public genesis address, fixtures only


def ticker(symbol="sBTCUSDT", price=60000, ts=None):
    return {"spot_market24h": {"symbol": symbol, "lastEp": int(price * 1e8),
                              "timestamp": int((time.time() if ts is None else ts) * 1e9)}}


def rule(**kwargs):
    return normalize_alert(dict({"id": "watch-a", "threshold": 100, "cooldown_sec": 0}, **kwargs))


def step(alert, state, price=100, now=1000, wallet=None, other=None):
    return evaluate_rule(alert, state, {"price": price}, wallet, other, now)


class FeedTests(unittest.TestCase):
    def test_scale_freshness_and_reject_derivatives(self):
        self.assertEqual(parse_ticker(ticker(price=123.45))[1]["price"], 123.45)
        for data in (ticker(ts=time.time()-60), ticker(ts=time.time()+60),
                     ticker(symbol="BTCUSD"), ticker(price=0), {"market24h": {}},
                     {"spot_market24h": {"symbol": "sBTCUSDT", "lastEp": "nan"}}):
            self.assertIsNone(parse_ticker(data))

    def test_derived_pair_needs_two_fresh_legs(self):
        feed = PhemexFeed()
        feed.ingest(ticker())
        self.assertIsNone(feed.quote("BTC/ETH"))
        feed.ingest(ticker("sETHUSDT", 3000))
        self.assertEqual(feed.quote("BTC/ETH")["price"], 20)
        self.assertTrue(feed.quote("BTC/ETH")["derived"])
        self.assertEqual(feed.quote("ETH/BTC")["price"], .05)
        self.assertFalse(feed.quote("BTC/USDT")["derived"])
        feed._prices["ETH/USDT"]["received"] -= 16
        self.assertIsNone(feed.quote("BTC/ETH"))

    def test_old_frames_do_not_overwrite_and_stop_clears(self):
        feed = PhemexFeed()
        now = time.time()
        feed.ingest(ticker(price=100, ts=now))
        feed.ingest(ticker(price=50, ts=now-1))
        self.assertEqual(feed.quote("BTC/USDT")["price"], 100)
        feed._status = "reconnecting"
        self.assertIsNone(feed.quote("BTC/USDT"))

    def test_reconnect_resubscribes_and_clears_old_quotes(self):
        sent = []
        second = threading.Event()
        class Socket:
            def __init__(self, number):
                self.number, self.count = number, 0
            def settimeout(self, timeout): pass
            def send(self, data): sent.append(json.loads(data))
            def close(self, **kwargs): pass
            def recv(self):
                self.count += 1
                if self.number == 1 and self.count == 1:
                    return json.dumps(ticker())
                if self.number == 2:
                    self.assert_empty = not feed._prices
                    feed._stop.set()
                    second.set()
                    return json.dumps({"result": "pong"})
                raise ConnectionError("fixture disconnect")
        sockets = []
        def connect(url, **kwargs):
            self.assertEqual(url, PHEMEX_URL)
            sock = Socket(len(sockets)+1)
            sockets.append(sock)
            return sock
        feed = PhemexFeed(connect=connect)
        feed.start()
        try:
            self.assertTrue(second.wait(4))
        finally:
            feed.stop()
        self.assertEqual(sum(s["method"] == "spot_market24h.subscribe" for s in sent), 2)
        self.assertTrue(sockets[1].assert_empty)
        self.assertIsNone(feed.quote("BTC/USDT"))


class RuleTests(unittest.TestCase):
    def test_crossing_latch_rearms_and_hit_limit(self):
        alert = rule(trigger_limit=2)
        state, message = step(alert, {})
        self.assertIsNotNone(message)
        state, message = step(alert, state, price=101)
        self.assertIsNone(message)
        state, _ = step(alert, state, price=90)
        state, message = step(alert, state, price=100)
        self.assertIsNotNone(message)
        state, _ = step(alert, state, price=90)
        state, message = step(alert, state, price=110)
        self.assertIsNone(message)
        self.assertEqual(state["hits"], 2)

    def test_independent_baselines_percent_delta_and_cooldown(self):
        alert = rule(trigger_type="price_change_above", change_percent=10, cooldown_sec=60)
        first, _ = step(alert, {}, price=100)
        second, _ = step(alert, {}, price=120)
        first, message = step(alert, first, price=111, now=1060)
        self.assertIsNotNone(message)
        second, message = step(alert, second, price=111, now=1060)
        self.assertIsNone(message)
        first, message = step(alert, first, price=125, now=1061)
        self.assertIsNone(message)
        first, message = step(alert, first, price=125, now=1120)
        self.assertIsNotNone(message)
        delta = rule(trigger_type="price_delta_below", change_absolute=5)
        state, _ = step(delta, {}, price=100)
        self.assertIsNotNone(step(delta, state, price=94)[1])

    def test_conversion_and_ratio_labels(self):
        alert = rule(trigger_type="asset_conversion", from_amount=.1, threshold=1.5)
        _, message = step(alert, {}, price=60000, other={"price": 3000})
        self.assertIn("2 ETH", message)
        alert = rule(pair="BTC/ETH", threshold=20)
        _, message = evaluate_rule(alert, {}, {"price": 21, "derived": True}, None, None, 1000)
        self.assertIn("21 ETH", message)
        self.assertIn("derived", message)

    def test_wallet_seed_pending_and_confirmed_no_net_change(self):
        alert = rule(trigger_type="wallet_change", address=ADDRESS)
        wallet = dict(confirmed_sats=100, confirmed_tx_count=1, pending_sats=0, pending_tx_count=0)
        state, message = step(alert, {}, wallet=wallet)
        self.assertIsNone(message)
        wallet.update(pending_sats=100, pending_tx_count=1)
        state, message = step(alert, state, wallet=wallet)
        self.assertIsNone(message)
        wallet.update(confirmed_tx_count=3)
        state, message = step(alert, state, wallet=wallet)
        self.assertIsNotNone(message)
        self.assertEqual(state["hits"], 1)
        self.assertIsNone(step(alert, deepcopy(state), wallet=wallet)[1])

    def test_validation_rejects_invalid_without_silent_defaults(self):
        for data in ({"threshold": "abc"}, {"threshold": "nan"}, {"threshold": -1},
                     {"pair": "../BTC"}, {"trigger_limit": 1.1}, {"active": "false"},
                     {"trigger_type": "wallet_change", "address": "private-key"}):
            with self.assertRaises(ValueError):
                rule(**data)
        self.assertEqual(rule(pair="btc/eth")["pair"], "BTC/ETH")


class WalletTests(unittest.TestCase):
    def test_parse_integer_satoshis_and_address_binding(self):
        stats = {"funded_txo_sum": 500, "spent_txo_sum": 300, "tx_count": 4}
        data = {"address": ADDRESS, "chain_stats": stats,
                "mempool_stats": {"funded_txo_sum": 0, "spent_txo_sum": 100, "tx_count": 1}}
        parsed = parse_address_stats(data, ADDRESS)
        self.assertEqual(parsed["confirmed_sats"], 200)
        self.assertEqual(parsed["pending_sats"], -100)
        with self.assertRaises(ValueError): parse_address_stats(data, "other")
        stats["tx_count"] = True
        with self.assertRaises(ValueError): parse_address_stats(data, ADDRESS)

    def test_https_only_address_only_and_bounded_request(self):
        self.assertEqual(validate_address(ADDRESS), ADDRESS)
        for url in ("http://localhost/api", "https://user:secret@example.com/api", "https://example.com/?key=x"):
            with self.assertRaises(ValueError): validate_api_url(url)
        with patch("crypto_alert.wallet.requests.get") as get:
            response = get.return_value.__enter__.return_value
            response.status_code = 200
            response.iter_content.return_value = [b"x" * 65537]
            with self.assertRaises(ValueError): fetch_address(ADDRESS)
            self.assertEqual(get.call_args.kwargs["timeout"], (5, 10))
            self.assertFalse(get.call_args.kwargs["allow_redirects"])


class FakeFeed:
    def __init__(self): self.price = 100
    def quote(self, pair): return {"price": self.price, "ts": time.time()} if self.price else None
    def status(self): return "live"


class EngineTests(unittest.TestCase):
    def make_engine(self, **kwargs):
        self.saved, self.messages = [], []
        self.feed = FakeFeed()
        def notify(message):
            self.messages.append(message)
            return True
        return AlertEngine(self.feed, lambda address: {}, lambda doc: self.saved.append(deepcopy(doc)), notify, **kwargs)

    def test_crud_revision_empty_list_restart_and_unchanged_runtime(self):
        engine = self.make_engine(initial=[rule()])
        engine.evaluate_once("watch-a")
        self.assertEqual(len(self.messages), 1)
        doc = engine.replace([rule()], 0)
        self.assertEqual(doc["runtime"]["watch-a"]["hits"], 1)
        with self.assertRaises(ValueError): engine.replace([], 0)
        engine.replace([], 1)
        saved = self.saved[-1]
        restored = self.make_engine(saved=saved, initial=[rule()])
        self.assertEqual(restored.snapshot()["watch_list"], [])

    def test_storage_failure_does_not_accept_edit_or_trigger(self):
        engine = self.make_engine(initial=[rule()])
        before = engine.snapshot()
        def fail(doc): raise OSError("fixture disk full")
        engine.persist = fail
        with self.assertRaises(OSError): engine.replace([], 0)
        self.assertEqual(engine.snapshot(), before)
        with self.assertRaises(OSError): engine.evaluate_once("watch-a")
        self.assertEqual(self.messages, [])

    def test_slow_wallet_is_independent_and_deleted_result_cannot_alert(self):
        engine = self.make_engine(initial=[rule(), rule(id="wallet", trigger_type="wallet_change", address=ADDRESS)])
        entered, release = threading.Event(), threading.Event()
        def fetch(address):
            entered.set()
            release.wait(3)
            return dict(confirmed_sats=100, confirmed_tx_count=1, pending_sats=0, pending_tx_count=0)
        engine.wallet_fetch = fetch
        engine.start()
        try:
            self.assertTrue(entered.wait(2))
            deadline = time.monotonic()+2
            while not self.messages and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(len(self.messages), 1)
            self.assertEqual(len(engine._workers), 2)
            engine.replace([rule()], 0)
            release.set()
        finally:
            release.set()
            engine.stop()
        self.assertNotIn("wallet", engine.snapshot()["runtime"])
        self.assertTrue(all(not t.is_alive() for t, _ in engine._workers.values()))

    def test_wallet_works_without_exchange_price(self):
        engine = self.make_engine(initial=[rule(trigger_type="wallet_change", address=ADDRESS)])
        self.feed.price = None
        wallet = dict(confirmed_sats=100, confirmed_tx_count=1, pending_sats=0, pending_tx_count=0)
        engine.wallet_fetch = lambda address: dict(wallet)
        engine.evaluate_once("watch-a")
        wallet["confirmed_sats"] = 200
        engine.evaluate_once("watch-a")
        self.assertEqual(len(self.messages), 1)
        self.assertNotIn("value_usdt", engine.snapshot()["live"]["watch-a"])

    def test_edit_restarts_sleeping_worker_and_resets_only_changed_rule(self):
        engine = self.make_engine(initial=[rule(threshold=200)])
        engine.start()
        try:
            original, stop = engine._workers["watch-a"]
            engine.replace([rule(threshold=300)], 0)
            self.assertTrue(stop.is_set())
            self.assertIsNot(engine._workers["watch-a"][0], original)
        finally:
            engine.stop()
        self.assertFalse(original.is_alive())

    def test_encrypted_store_survives_new_agent_id_and_rejects_bad_key(self):
        class Store(EncryptedStateMixin):
            def __init__(self, root, uid, key=b"k" * 32):
                self.command_line_args = {"universal_id": uid, "universe": "test"}
                self.path_resolution = {"root_path": root}
                self.tree_node = {"config": {"security": {"persistent_state": {
                    "state_id": "crypto-test", "key": base64.b64encode(key).decode(),
                    "algorithm": "AES-256-GCM", "key_version": 1}}}}
                self.init_encrypted_state(namespace="crypto_alerts")
        with tempfile.TemporaryDirectory() as directory:
            first = Store(directory, "old-uid")
            engine = self.make_engine(initial=[rule()])
            engine.persist = lambda doc: first.save_encrypted_state("watches", doc)
            engine.evaluate_once("watch-a")
            second = Store(directory, "new-uid")
            restored = self.make_engine(saved=second.load_encrypted_state("watches"))
            restored.evaluate_once("watch-a")
            self.assertEqual(self.messages, [])
            disk = next(Path(directory).rglob("*.aes")).read_text()
            self.assertNotIn("watch-a", disk)
            wrong = Store(directory, "new-uid", key=b"z" * 32)
            with self.assertRaises(EncryptedStateError): wrong.load_encrypted_state("watches")


if __name__ == "__main__":
    unittest.main()
