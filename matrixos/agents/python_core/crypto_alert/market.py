"""Public Phemex spot prices shared by all alert workers (no trading API)."""
from __future__ import annotations

import json
import math
import re
import threading
import time

import websocket


# Public endpoint migration: https://phemex.com/announcements/phemex-updates-api-entry-endpoints
PHEMEX_URL = "wss://ws.phemex.com"
MAX_QUOTE_AGE = 15
PAIR_RE = re.compile(r"^[A-Z0-9]{2,16}/[A-Z0-9]{2,16}$")


def normalize_pair(pair):
    value = str(pair).strip().upper()
    if not PAIR_RE.fullmatch(value):
        raise ValueError("Use a pair such as BTC/USDT or BTC/ETH")
    return value


def parse_ticker(message, now=None):
    """Phemex spot Ep prices use scale 8; derivatives use another protocol."""
    now = time.time() if now is None else now
    ticker = message.get("spot_market24h")
    if not isinstance(ticker, dict):
        return None
    symbol = ticker.get("symbol", "")
    if not isinstance(symbol, str) or not re.fullmatch(r"s[A-Z0-9]{2,16}USDT", symbol):
        return None
    try:
        price = float(ticker["lastEp"]) / 100_000_000
        timestamp = float(ticker.get("timestamp", message.get("timestamp", 0))) / 1_000_000_000
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(price) or price <= 0 or not math.isfinite(timestamp):
        return None
    if timestamp < now - MAX_QUOTE_AGE or timestamp > now + 10:
        return None
    return symbol[1:-4] + "/USDT", {"price": price, "ts": timestamp}


class PhemexFeed:
    def __init__(self, connect=None):
        self._connect = connect or websocket.create_connection
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._socket = None
        self._prices = {}
        self._status = "stopped"

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="phemex-prices", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            sock = self._socket
        if sock:
            try:
                sock.close(timeout=1)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=12)

    def status(self):
        with self._lock:
            return self._status

    def quote(self, pair):
        with self._lock:
            base, currency = normalize_pair(pair).split("/")
            if self._status != "live":
                return None
            def usdt(asset):
                if asset == "USDT":
                    return {"price": 1.0, "ts": time.time()}
                value = self._prices.get(asset + "/USDT")
                if (not value or time.monotonic() - value["received"] > MAX_QUOTE_AGE
                        or time.time() - value["ts"] > MAX_QUOTE_AGE):
                    return None
                return value
            left, right = usdt(base), usdt(currency)
            if not left or not right:
                return None
            return {"price": left["price"] / right["price"],
                    "ts": min(left["ts"], right["ts"]),
                    "derived": currency != "USDT"}

    def ingest(self, message):
        result = parse_ticker(message)
        if not result:
            return
        pair, quote = result
        with self._lock:
            previous = self._prices.get(pair)
            if previous and quote["ts"] <= previous["ts"]:
                return
            self._prices[pair] = dict(quote, received=time.monotonic())
            self._status = "live"

    def _run(self):
        retry = 1
        while not self._stop.is_set():
            sock = None
            try:
                with self._lock:
                    self._status = "connecting"
                    self._prices.clear()
                sock = self._connect(PHEMEX_URL, timeout=10, enable_multithread=True)
                sock.settimeout(1)
                with self._lock:
                    self._socket = sock
                    self._status = "awaiting prices"
                sock.send(json.dumps({"id": 1, "method": "spot_market24h.subscribe", "params": []}))
                last_ping = last_message = time.monotonic()
                while not self._stop.is_set():
                    now = time.monotonic()
                    if now - last_ping >= 5:
                        sock.send(json.dumps({"id": 2, "method": "server.ping", "params": []}))
                        last_ping = now
                    if now - last_message > 15:
                        raise TimeoutError("Phemex heartbeat expired")
                    try:
                        raw = sock.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if not raw or len(raw) > 1_000_000:
                        raise ValueError("Invalid Phemex frame")
                    message = json.loads(raw)
                    if not isinstance(message, dict) or message.get("error"):
                        raise ValueError("Phemex subscription rejected")
                    last_message = time.monotonic()
                    self.ingest(message)
                    retry = 1
            except Exception as exc:
                with self._lock:
                    self._status = f"reconnecting ({type(exc).__name__})"
                    self._prices.clear()
            finally:
                with self._lock:
                    self._socket = None
                if sock:
                    try:
                        sock.close(timeout=1)
                    except Exception:
                        pass
            if self._stop.wait(retry):
                break
            retry = min(30, retry * 2)
        with self._lock:
            self._status = "stopped"
            self._prices.clear()
