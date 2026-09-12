"""Persistent alert rules and independent, stoppable watch workers."""
from __future__ import annotations

from copy import deepcopy
import math
import re
import threading
import time
import uuid

from crypto_alert.market import normalize_pair
from crypto_alert.wallet import validate_address


MAX_ALERTS = 64
TRIGGERS = {"price_above", "price_below", "price_change_above", "price_change_below",
            "price_delta_above", "price_delta_below", "asset_conversion", "wallet_change"}


def number(value, name, minimum=0, maximum=1e18):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if isinstance(value, bool) or not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return result


def normalize_alert(raw):
    if not isinstance(raw, dict):
        raise ValueError("Each alert must be an object")
    uid = raw.get("id") or uuid.uuid4().hex
    if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", uid):
        raise ValueError("Invalid alert ID")
    trigger = raw.get("trigger_type", "price_above")
    if trigger not in TRIGGERS:
        raise ValueError("Unsupported alert trigger")
    alert = {"id": uid, "trigger_type": trigger}
    label = raw.get("label", "")
    if not isinstance(label, str) or len(label) > 100:
        raise ValueError("Alert label must be at most 100 characters")
    alert["label"] = label.strip()
    for key in ("active", "alert_enabled", "stream_enabled"):
        value = raw.get(key, True)
        if type(value) not in (bool, int) or value not in (True, False, 0, 1):
            raise ValueError(f"{key} must be on or off")
        alert[key] = bool(value)
    limit = number(raw.get("trigger_limit", 0), "Trigger limit", maximum=9999999)
    if not limit.is_integer():
        raise ValueError("Trigger limit must be a whole number (0 means unlimited)")
    alert["trigger_limit"] = int(limit)
    alert["cooldown_sec"] = number(raw.get("cooldown_sec", 60), "Cooldown", 0, 86400)
    if trigger == "wallet_change":
        alert["address"] = validate_address(raw.get("address", ""))
        alert["poll_interval"] = number(raw.get("poll_interval", 60), "Wallet interval", 30, 3600)
        alert["pair"] = "BTC/USDT"
    elif trigger == "asset_conversion":
        for field, default in (("from_asset", "BTC"), ("to_asset", "ETH")):
            asset = str(raw.get(field, default)).strip().upper()
            normalize_pair(asset + "/USDT")
            alert[field] = asset
        alert["pair"] = alert["from_asset"] + "/USDT"
        alert["from_amount"] = number(raw.get("from_amount", 0.1), "Amount", 1e-12)
        alert["threshold"] = number(raw.get("threshold", 1), "Conversion threshold", 1e-12)
    else:
        alert["pair"] = normalize_pair(raw.get("pair", "BTC/USDT"))
        key = ("change_percent" if trigger.startswith("price_change") else
               "change_absolute" if trigger.startswith("price_delta") else "threshold")
        alert[key] = number(raw.get(key, 1), key, 1e-12)
    return alert


class AlertEngine:
    def __init__(self, feed, wallet_fetch, persist, notify, saved=None, initial=None):
        self.feed, self.wallet_fetch = feed, wallet_fetch
        self.persist, self.notify = persist, notify
        self._lock = threading.RLock()
        self._stopping = threading.Event()
        self._workers = {}
        self._retired = []
        self._live = {}
        self._started = False
        if saved is None:
            alerts = self._validate_list(initial or [])
            self._document = {"version": 1, "revision": 0, "alerts": alerts, "runtime": {}}
            self.persist(deepcopy(self._document))
        else:
            if not isinstance(saved, dict) or saved.get("version") != 1:
                raise ValueError("Unsupported crypto watch state")
            if type(saved.get("revision")) is not int or saved["revision"] < 0:
                raise ValueError("Invalid crypto state revision")
            if not isinstance(saved.get("runtime"), dict):
                raise ValueError("Invalid crypto runtime state")
            self._document = deepcopy(saved)
            self._document["alerts"] = self._validate_list(saved.get("alerts"))

    @staticmethod
    def _validate_list(alerts):
        if not isinstance(alerts, list) or len(alerts) > MAX_ALERTS:
            raise ValueError(f"Watch list must contain at most {MAX_ALERTS} alerts")
        normalized = [normalize_alert(alert) for alert in alerts]
        if len({a["id"] for a in normalized}) != len(normalized):
            raise ValueError("Duplicate alert IDs")
        return normalized

    def snapshot(self):
        with self._lock:
            return {"revision": self._document["revision"],
                    "watch_list": deepcopy(self._document["alerts"]),
                    "runtime": deepcopy(self._document["runtime"]),
                    "live": deepcopy(self._live), "feed_status": self.feed.status()}

    def replace(self, alerts, expected_revision):
        normalized = self._validate_list(alerts)
        with self._lock:
            if type(expected_revision) is not int or expected_revision != self._document["revision"]:
                raise ValueError("Alerts changed in another panel; reload before saving")
            prior = {a["id"]: a for a in self._document["alerts"]}
            runtime = {a["id"]: deepcopy(self._document["runtime"].get(a["id"], {}))
                       for a in normalized if prior.get(a["id"]) == a}
            updated = {"version": 1, "revision": expected_revision + 1,
                       "alerts": normalized, "runtime": runtime}
            self.persist(deepcopy(updated))  # disk commit precedes success acknowledgment
            self._document = updated
            self._live = {key: value for key, value in self._live.items() if key in runtime}
            # Wake changed watches immediately, even if their old wallet worker
            # was sleeping for a long polling interval.
            current = {a["id"]: a for a in normalized}
            for uid in list(self._workers):
                if current.get(uid) != prior.get(uid):
                    thread, stop = self._workers.pop(uid)
                    stop.set()
                    self._retired.append(thread)
            self._sync_workers()
            return self.snapshot()

    def start(self):
        with self._lock:
            self._started = True
            self._sync_workers()

    def maintain(self):
        with self._lock:
            self._sync_workers()

    def _sync_workers(self):
        if not self._started or self._stopping.is_set():
            return
        wanted = {a["id"] for a in self._document["alerts"] if a["active"]}
        for uid in list(self._workers):
            if uid not in wanted:
                thread, stop = self._workers.pop(uid)
                stop.set()
                self._retired.append(thread)
        self._retired = [thread for thread in self._retired if thread.is_alive()]
        for uid in wanted:
            # Bound old workers that may still be finishing a network request.
            if uid in self._workers or len(self._workers) + len(self._retired) >= MAX_ALERTS * 2:
                continue
            stop = threading.Event()
            thread = threading.Thread(target=self._loop, args=(uid, stop),
                                      name=f"crypto-watch-{uid}", daemon=True)
            self._workers[uid] = (thread, stop)
            thread.start()

    def stop(self):
        self._stopping.set()
        with self._lock:
            for thread, stop in self._workers.values():
                stop.set()
            threads = [t for t, _ in self._workers.values()] + self._retired
        deadline = time.monotonic() + 16
        for thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))

    def _loop(self, uid, stop):
        while not stop.is_set() and not self._stopping.is_set():
            try:
                delay = self.evaluate_once(uid, stop)
            except Exception as exc:
                with self._lock:
                    if not stop.is_set() and any(a["id"] == uid for a in self._document["alerts"]):
                        self._live[uid] = {"status": f"Watch error: {type(exc).__name__}"}
                delay = 30
            if stop.wait(delay):
                break

    def evaluate_once(self, uid, stop=None):
        with self._lock:
            alert = next((a for a in self._document["alerts"] if a["id"] == uid), None)
            if alert is None or not alert["active"]:
                return 1
            runtime = deepcopy(self._document["runtime"].get(uid, {}))
        is_wallet = alert["trigger_type"] == "wallet_change"
        quote = self.feed.quote(alert["pair"])
        wallet = self.wallet_fetch(alert["address"]) if is_wallet else None
        other = (self.feed.quote(alert["to_asset"] + "/USDT")
                 if alert["trigger_type"] == "asset_conversion" else None)
        now = time.time()
        live = {"status": "watching", "ts": now}
        if quote:
            live.update(price=quote["price"], price_ts=quote["ts"], derived=quote.get("derived", False))
        if wallet:
            live.update(wallet)
            if quote:
                live["value_usdt"] = wallet["confirmed_sats"] / 1e8 * quote["price"]
        if not is_wallet and (not quote or (alert["trigger_type"] == "asset_conversion" and not other)):
            with self._lock:
                if alert in self._document["alerts"]:
                    self._live[uid] = {"status": "waiting for fresh Phemex spot price"}
            return 1

        next_state, message = evaluate_rule(alert, runtime, quote, wallet, other, now)
        if other:
            live["conversion_value"] = alert["from_amount"] * quote["price"] / other["price"]
        with self._lock:
            # Reject a result fetched before an edit/delete/pause or worker shutdown.
            if (self._stopping.is_set() or (stop and stop.is_set())
                    or not any(a is alert for a in self._document["alerts"])):
                return 1
            if next_state != runtime:
                document = deepcopy(self._document)
                document["runtime"][uid] = next_state
                self.persist(document)
                self._document["runtime"][uid] = next_state
            if alert["trigger_limit"] and next_state.get("hits", 0) >= alert["trigger_limit"]:
                live["status"] = "trigger limit reached"
            elif not alert["alert_enabled"]:
                live["status"] = "watching (notifications off)"
            self._live[uid] = live
        if message:
            delivered = False
            try:
                delivered = bool(self.notify(message))
            finally:
                with self._lock:
                    current = self._document["runtime"].get(uid)
                    if current and current.get("event_id") == next_state["event_id"]:
                        document = deepcopy(self._document)
                        document["runtime"][uid]["delivery"] = "queued" if delivered else "failed"
                        self.persist(document)
                        self._document["runtime"][uid] = document["runtime"][uid]
        return alert.get("poll_interval", 1)


def evaluate_rule(alert, state, quote, wallet, other, now):
    """Pure rule evaluation. Baselines and crossing latches belong to alert IDs."""
    state = deepcopy(state)
    trigger = alert["trigger_type"]
    condition, detail = False, ""
    if trigger == "wallet_change":
        previous = state.get("wallet")
        # Pending transactions are shown but only confirmations trigger notices.
        observed = {k: wallet[k] for k in ("confirmed_sats", "confirmed_tx_count")}
        condition = previous is not None and observed != previous
        if condition:
            delta = (observed["confirmed_sats"] - previous["confirmed_sats"]) / 1e8
            detail = (f"Bitcoin address {alert['address'][:8]}…{alert['address'][-6:]}: "
                      f"confirmed balance changed by {delta:+.8f} BTC; "
                      f"balance {observed['confirmed_sats'] / 1e8:.8f} BTC; "
                      f"confirmed transactions {observed['confirmed_tx_count']}.")
        # Preserve pending changes during cooldown, report net change next interval.
        if previous is None or not condition or not alert["alert_enabled"]:
            state["wallet"] = observed
    else:
        price = quote["price"]
        currency = alert["pair"].split("/")[1]
        baseline = state.setdefault("baseline", price)
        if trigger == "asset_conversion":
            value = alert["from_amount"] * price / other["price"]
            condition = value >= alert["threshold"]
            detail = f"{alert['from_amount']:g} {alert['from_asset']} = {value:.8g} {alert['to_asset']}"
        elif trigger.startswith("price_change") or trigger.startswith("price_delta"):
            change = price - baseline
            value = change / baseline * 100 if trigger.startswith("price_change") else change
            threshold = alert["change_percent"] if trigger.startswith("price_change") else alert["change_absolute"]
            condition = value >= threshold if trigger.endswith("above") else value <= -threshold
            unit = "%" if trigger.startswith("price_change") else f" {currency}"
            detail = f"{alert['pair']} moved {value:+.6g}{unit} since armed baseline {baseline:.8g}; now {price:.8g} {currency}"
        else:
            condition = price >= alert["threshold"] if trigger == "price_above" else price <= alert["threshold"]
            detail = f"{alert['pair']} reached {price:.8g} {currency} ({trigger}, threshold {alert['threshold']:.8g})"
        if quote.get("derived"):
            detail += " (derived from Phemex USDT spot prices)"
        if not condition:
            state["latched"] = False
    limited = alert["trigger_limit"] and state.get("hits", 0) >= alert["trigger_limit"]
    crossing = trigger in ("price_above", "price_below", "asset_conversion")
    allowed = (condition and alert["alert_enabled"] and not limited
               and (not crossing or not state.get("latched", False))
               and now - state.get("last_trigger", 0) >= alert["cooldown_sec"])
    if not allowed:
        return state, None
    state.update(hits=state.get("hits", 0) + 1, last_trigger=now,
                 event_id=uuid.uuid4().hex, delivery="pending")
    if trigger == "wallet_change":
        state["wallet"] = observed
    elif crossing:
        state["latched"] = True
    else:
        state["baseline"] = quote["price"]
    label = alert["label"] or alert["pair"]
    return state, f"{label}: {detail}\nAlert {alert['id']} · hit {state['hits']}"
