"""Persistent calendar reminders. A relay queue acknowledgement is not final delivery."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
import threading
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_ALARMS = 200


def _local_instant(local, zone):
    """Choose first occurrence of an ambiguous time; reject nonexistent wall times."""
    aware = local.replace(tzinfo=zone, fold=0)
    utc = aware.astimezone(UTC)
    if utc.astimezone(zone).replace(tzinfo=None) != local:
        raise ValueError("This local time does not exist in the selected time zone")
    return utc


def normalize_alarm(raw):
    if not isinstance(raw, dict):
        raise ValueError("Alarm must be an object")
    uid = raw.get("id") or uuid.uuid4().hex
    if not isinstance(uid, str) or not ID.fullmatch(uid):
        raise ValueError("Invalid alarm ID")
    title, message = raw.get("title", ""), raw.get("message", "")
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise ValueError("Title is required and must be at most 120 characters")
    if not isinstance(message, str) or not message.strip() or len(message) > 2000:
        raise ValueError("Message is required and must be at most 2000 characters")
    zone_name = raw.get("timezone")
    if not isinstance(zone_name, str) or len(zone_name) > 100:
        raise ValueError("An IANA time zone is required")
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Unknown IANA time zone") from None
    start = raw.get("start_local")
    try:
        local = datetime.fromisoformat(start)
        if local.tzinfo is not None or local.second or local.microsecond:
            raise ValueError()
        _local_instant(local, zone)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Start must be a valid local date and time (minute precision)") from None
    repeat = raw.get("repeat", "once")
    if repeat not in ("once", "daily", "weekly"):
        raise ValueError("Repeat must be once, daily, or weekly")
    enabled = raw.get("enabled", True)
    if type(enabled) is not bool:
        raise ValueError("Enabled must be true or false")
    result = {"id": uid, "title": title.strip(), "message": message.strip(),
            "start_local": local.isoformat(timespec="minutes"), "timezone": zone_name,
            "repeat": repeat, "enabled": enabled}
    if "alert_role" in raw:
        role = raw["alert_role"]
        if not isinstance(role, str) or not role.strip() or len(role) > 128 or "@" in role:
            raise ValueError("Enter a service role without a handler, such as hive.alert")
        result["alert_role"] = role.strip()
    else:
        # Existing alarms keep their explicit targets until the operator opts in
        # to service-role routing; never silently broaden their recipients.
        destinations = raw.get("destinations")
        if (not isinstance(destinations, list) or not destinations or len(destinations) > 32
                or any(not isinstance(x, str) or not ID.fullmatch(x) for x in destinations)
                or len(set(destinations)) != len(destinations)):
            raise ValueError("Select at least one distinct alert destination")
        result["destinations"] = list(destinations)
    return result


def _schedule_key(alarm):
    return tuple(alarm[k] for k in ("start_local", "timezone", "repeat"))


def _next_after(alarm, now):
    """Return the first future calendar occurrence; skip DST gaps and coalesce missed repeats."""
    if alarm["repeat"] == "once":
        return None
    zone = ZoneInfo(alarm["timezone"])
    start = datetime.fromisoformat(alarm["start_local"])
    days = 1 if alarm["repeat"] == "daily" else 7
    local_now = now.astimezone(zone).replace(tzinfo=None)
    count = max(0, (local_now.date() - start.date()).days // days)
    for offset in range(count, count + 4):
        try:
            candidate = _local_instant(start + timedelta(days=offset * days), zone)
        except (ValueError, OverflowError):
            continue
        if candidate > now:
            return candidate.isoformat()
    raise ValueError("Could not calculate the next occurrence")


class AlarmEngine:
    def __init__(self, persist, notify, saved=None, resolve_destinations=None):
        self.persist, self.notify = persist, notify
        self.resolve_destinations = resolve_destinations
        self.lock = threading.RLock()
        if saved is None:
            self.doc = {"version": 1, "revision": 0, "alarms": [], "runtime": {}}
            self.persist(deepcopy(self.doc))
        else:
            if (not isinstance(saved, dict) or saved.get("version") != 1
                    or type(saved.get("revision")) is not int or saved["revision"] < 0
                    or not isinstance(saved.get("runtime"), dict)):
                raise ValueError("Invalid alarm state")
            self.doc = deepcopy(saved)
            self.doc["alarms"] = self._validate(saved.get("alarms"))

    @staticmethod
    def _validate(alarms):
        if not isinstance(alarms, list) or len(alarms) > MAX_ALARMS:
            raise ValueError(f"At most {MAX_ALARMS} alarms are supported")
        result = [normalize_alarm(a) for a in alarms]
        if len({a["id"] for a in result}) != len(result):
            raise ValueError("Duplicate alarm ID")
        return result

    def snapshot(self):
        with self.lock:
            return {"revision": self.doc["revision"], "alarms": deepcopy(self.doc["alarms"]),
                    "runtime": deepcopy(self.doc["runtime"])}

    def replace(self, alarms, revision):
        alarms = self._validate(alarms)
        with self.lock:
            if type(revision) is not int or revision != self.doc["revision"]:
                raise ValueError("Alarms changed in another panel; reload before saving")
            old = {a["id"]: a for a in self.doc["alarms"]}
            runtime = {}
            for alarm in alarms:
                previous = old.get(alarm["id"])
                if previous and _schedule_key(previous) == _schedule_key(alarm):
                    state = deepcopy(self.doc["runtime"].get(alarm["id"], {}))
                    # Keep an in-flight occurrence across edits. Already queued
                    # destinations stay complete; newly selected ones are pending.
                    pending = state.get("pending")
                    if isinstance(pending, dict) and previous.get("alert_role") != alarm.get("alert_role"):
                        # Routing changed: re-resolve without resending to any
                        # already-queued targets common to both recipient sets.
                        pending.pop("destinations", None)
                    if isinstance(pending, dict) and "destinations" in alarm:
                        pending["queued"] = [uid for uid in pending.get("queued", [])
                                             if uid in alarm["destinations"]]
                        pending.pop("destinations", None)
                    runtime[alarm["id"]] = state
            updated = {"version": 1, "revision": revision + 1, "alarms": alarms, "runtime": runtime}
            self.persist(deepcopy(updated))
            self.doc = updated
            return self.snapshot()

    def tick(self, now=None):
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("now must be timezone aware")
        now = now.astimezone(UTC)
        with self.lock:
            for alarm in self.doc["alarms"]:
                if not alarm["enabled"]:
                    continue
                uid = alarm["id"]
                state = deepcopy(self.doc["runtime"].get(uid, {}))
                if "next_at" not in state:
                    local = datetime.fromisoformat(alarm["start_local"])
                    state["next_at"] = _local_instant(local, ZoneInfo(alarm["timezone"])).isoformat()
                if not state.get("pending") and state.get("next_at"):
                    due = datetime.fromisoformat(state["next_at"])
                    if due <= now:
                        state["pending"] = {"occurrence": due.isoformat(), "queued": []}
                        state["next_at"] = _next_after(alarm, now)
                updated = deepcopy(self.doc)
                updated["runtime"][uid] = state
                if updated != self.doc:
                    self.persist(deepcopy(updated))
                    self.doc = updated
                pending = state.get("pending")
                if not pending:
                    continue
                destinations = pending.get("destinations")
                if destinations is None:
                    if "destinations" in alarm:
                        destinations = alarm["destinations"]
                    else:
                        try:
                            destinations = list(self.resolve_destinations(alarm)) if self.resolve_destinations else []
                        except Exception:
                            destinations = []
                    # With no matching listeners, retain the occurrence and retry.
                    if not destinations:
                        continue
                    pending["destinations"] = destinations
                    updated = deepcopy(self.doc)
                    updated["runtime"][uid] = deepcopy(state)
                    self.persist(deepcopy(updated))
                    self.doc = updated
                for destination in destinations:
                    if destination in pending["queued"]:
                        continue
                    try:
                        queued = self.notify(deepcopy(alarm), destination, pending["occurrence"])
                    except Exception:
                        queued = False
                    if queued:
                        pending["queued"].append(destination)
                        updated = deepcopy(self.doc)
                        updated["runtime"][uid] = deepcopy(state)
                        self.persist(deepcopy(updated))
                        self.doc = updated
                if set(destinations).issubset(pending["queued"]):
                    state["last_queued"] = pending["occurrence"]
                    state.pop("pending", None)
                    updated = deepcopy(self.doc)
                    updated["runtime"][uid] = state
                    self.persist(deepcopy(updated))
                    self.doc = updated
