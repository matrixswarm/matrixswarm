"""Encrypted, agent-scoped scheduled reminders for configured swarm relays."""
from __future__ import annotations

import os
import re
import sys
import time

for path in (os.getenv("SITE_ROOT"), os.getenv("AGENT_PATH")):
    if path:
        sys.path.insert(0, path)

from core.python_core.boot_agent import BootAgent
from core.python_core.mixin.encrypted_state import EncryptedStateMixin
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from core.python_core.utils.swarm_sleep import interruptible_sleep
from global_alarm.engine import AlarmEngine


class Agent(EncryptedStateMixin, BootAgent):
    def __init__(self):
        super().__init__()
        cfg = self.tree_node.get("config", {}) or {}
        self.name = "GlobalAlarm"
        self._alert_role = cfg.get("alert_role", "hive.alert")
        self._rpc_role = cfg.get("rpc_router_role", "hive.rpc")
        self.interval = max(1, min(60, int(cfg.get("interval_sec", 5))))
        self.init_encrypted_state(namespace="global_alarm")
        saved = self.load_encrypted_state("alarms", default=None)
        self.engine = AlarmEngine(lambda state: self.save_encrypted_state("alarms", state),
                                  self._queue_alert, saved=saved,
                                  resolve_destinations=self._alarm_destinations)
        self._emit_beacon = self.check_for_thread_poke("worker", timeout=max(60, self.interval * 3),
                                                       emit_to_file_interval=10)

    def _authorized(self, content, identity):
        return (isinstance(content, dict)
                and content.get("target_universal_id") == self.command_line_args.get("universal_id")
                and isinstance(identity, IdentityObject) and identity.has_verified_identity()
                and identity.get_sender_uid() == self.get_matrix_universal_id())

    @staticmethod
    def _callback_fields(content):
        for key in ("session_id", "token", "request_id"):
            value = content.get(key)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
                raise ValueError(f"Invalid {key}")
        return content["session_id"], content["token"]

    def _destinations(self, role=None):
        endpoints = self.get_nodes_by_role(role or self._alert_role) or []
        return sorted({endpoint.get_universal_id() for endpoint in endpoints
                       if endpoint.get_universal_id()})

    def _alarm_destinations(self, alarm):
        return self._destinations(alarm.get("alert_role"))

    @staticmethod
    def _server_clock():
        """Report the server clock and, where available, its IANA zone name."""
        from datetime import datetime
        from pathlib import Path

        now = datetime.now().astimezone()
        zone = os.environ.get("TZ", "").lstrip(":")
        if not zone:
            localtime = os.path.realpath("/etc/localtime")
            marker = "/zoneinfo/"
            if marker in localtime:
                zone = localtime.split(marker, 1)[1]
            else:
                try:
                    zone = Path("/etc/timezone").read_text(encoding="utf-8").strip()
                except (OSError, UnicodeError):
                    zone = ""
        # Do not expose a TZ file path or arbitrary environment data.
        if not re.fullmatch(r"[A-Za-z0-9_+./-]{1,128}", zone) or zone.startswith("/") or ".." in zone:
            zone = ""
        return {"local_time": now.isoformat(timespec="seconds"),
                "timezone": zone, "abbreviation": now.tzname() or ""}

    def _reply(self, content, payload, handler="global_alarm.config"):
        session, token = self._callback_fields(content)
        return self.crypto_reply(response_handler=handler,
            payload=dict(payload, agent_uid=self.command_line_args["universal_id"], token=token,
                         request_id=content["request_id"]),
            session_id=session, token=token, rpc_role=self._rpc_role, quiet=True)

    def cmd_get_alarms(self, content, packet, identity=None):
        if not self._authorized(content, identity):
            return
        snapshot = self.engine.snapshot()
        if content.get("clock_only") is True:
            self._reply(content, {"ok": True, "server_clock": self._server_clock(),
                                  "revision": snapshot["revision"], "runtime": snapshot["runtime"]},
                        handler="global_alarm.clock")
            return
        self._reply(content, dict(snapshot, ok=True, destinations=self._destinations(),
                                  default_alert_role=self._alert_role, server_clock=self._server_clock()))

    def cmd_update_alarms(self, content, packet, identity=None):
        if not self._authorized(content, identity):
            return
        self._callback_fields(content)
        try:
            snapshot = self.engine.replace(content.get("alarms"), content.get("revision"))
        except ValueError as exc:
            self._reply(content, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:
            self.log(f"[GLOBAL-ALARM] Save failed: {type(exc).__name__}", level="ERROR")
            self._reply(content, {"ok": False, "error": "Could not save encrypted state"})
            return
        self._reply(content, dict(snapshot, ok=True, destinations=self._destinations(),
                                  default_alert_role=self._alert_role, server_clock=self._server_clock()))

    def _queue_alert(self, alarm, destination, occurrence):
        for endpoint in self.get_nodes_by_role(alarm.get("alert_role") or self._alert_role) or []:
            if endpoint.get_universal_id() != destination:
                continue
            notification = self.get_delivery_packet("notify.alert.general")
            notification.set_data({"timestamp": occurrence,
                "universal_id": self.command_line_args["universal_id"], "level": "info",
                "msg": f"⏰ {alarm['title']}\n{alarm['message']}",
                "cause": "Global Alarm", "origin": self.command_line_args["universal_id"]})
            packet = self.get_delivery_packet("standard.command.packet")
            packet.set_data({"handler": endpoint.get_handler()})
            packet.set_auto_fill_sub_packet(False)
            packet.set_packet(notification, "content")
            return bool(self.pass_packet(packet, destination))
        return False

    def worker(self, config=None, identity=None):
        self._emit_beacon()
        try:
            self.engine.tick()
        except Exception as exc:
            self.log(f"[GLOBAL-ALARM] Scheduler error: {type(exc).__name__}", level="ERROR")
        interruptible_sleep(self, self.interval)


if __name__ == "__main__":
    Agent().boot()
