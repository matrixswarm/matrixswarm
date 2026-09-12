"""Phemex price alerts and Bitcoin address watches controlled by Phoenix."""
from __future__ import annotations

import os
import sys
for _path in (os.getenv("SITE_ROOT"), os.getenv("AGENT_PATH")):
    if _path:
        sys.path.insert(0, _path)

import re
import threading
import time

from core.python_core.boot_agent import BootAgent
from core.python_core.mixin.encrypted_state import EncryptedStateMixin
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from crypto_alert.engine import AlertEngine
from crypto_alert.market import PhemexFeed
from crypto_alert.wallet import DEFAULT_API, fetch_address, validate_api_url


class Agent(EncryptedStateMixin, BootAgent):
    def __init__(self):
        super().__init__()
        config = self.tree_node.get("config", {})
        self.name = "CryptoAlert"
        self._rpc_role = config.get("rpc_router_role", "hive.rpc")
        self._alert_role = config.get("alert_role", "hive.alert")
        self._bitcoin_api = validate_api_url(config.get("bitcoin_api_url", DEFAULT_API))
        self._streams = {}
        self._stream_lock = threading.RLock()
        self._last_stream = 0
        self.init_encrypted_state(namespace="crypto_alerts")
        saved = self.load_encrypted_state("watches", default=None)
        self.feed = PhemexFeed()
        self.engine = AlertEngine(
            self.feed,
            lambda address: fetch_address(address, self._bitcoin_api),
            lambda state: self.save_encrypted_state("watches", state),
            self.send_simple_alert,
            saved=saved, initial=config.get("watch_list", []),
        )
        self.log(f"[CRYPTO] Restored {len(self.engine.snapshot()['watch_list'])} watches; "
                 f"persistent state {self._encrypted_state_identity}.")

    def _authorized(self, content, identity):
        # Matrix signs service requests. The target guard isolates multiple
        # crypto instances even though the service router fans out by role.
        return (isinstance(content, dict)
                and content.get("target_universal_id") == self.command_line_args.get("universal_id")
                and isinstance(identity, IdentityObject)
                and identity.has_verified_identity()
                and identity.get_sender_uid() == self.get_matrix_universal_id())

    @staticmethod
    def _callback_fields(content):
        for key in ("session_id", "token", "request_id"):
            value = content.get(key)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
                raise ValueError(f"Invalid {key}")
        return content["session_id"], content["token"]

    def _reply(self, content, payload, handler="crypto_alert.config"):
        session, token = self._callback_fields(content)
        return self.crypto_reply(
            response_handler=handler,
            payload=dict(payload, agent_uid=self.command_line_args["universal_id"],
                         token=token, request_id=content["request_id"]),
            session_id=session, token=token, rpc_role=self._rpc_role, quiet=True,
        )

    def cmd_retrieve_config(self, content, packet, identity=None):
        if not self._authorized(content, identity):
            return
        self._reply(content, dict(self.engine.snapshot(), ok=True))

    def cmd_update_alerts(self, content, packet, identity=None):
        if not self._authorized(content, identity):
            return
        self._callback_fields(content)
        try:
            snapshot = self.engine.replace(content.get("watch_list"), content.get("revision"))
        except ValueError as exc:
            self._reply(content, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:
            self.log(f"[CRYPTO] Cannot persist watches: {type(exc).__name__}", level="ERROR")
            self._reply(content, {"ok": False, "error": "Could not save encrypted state; changes were not accepted"})
            return
        self._reply(content, dict(snapshot, ok=True))

    def cmd_stream_prices(self, content, packet, identity=None):
        if not self._authorized(content, identity):
            return
        session, token = self._callback_fields(content)
        with self._stream_lock:
            key = (session, token)
            if key not in self._streams and len(self._streams) >= 32:
                return
            self._streams[key] = (dict(content), time.monotonic() + 60)

    def cmd_stop_stream_prices(self, content, packet, identity=None):
        if not self._authorized(content, identity):
            return
        key = self._callback_fields(content)
        with self._stream_lock:
            self._streams.pop(key, None)

    def worker_pre(self):
        self.feed.start()
        self.engine.start()
        self.log("[CRYPTO] Phemex spot feed and independent watch workers started.")

    def worker(self, config=None, identity=None):
        # Saved watches are authoritative; do not overwrite them on each tick
        # with the original deployment config.
        self.engine.maintain()
        now = time.monotonic()
        if now - self._last_stream < 2:
            return
        self._last_stream = now
        with self._stream_lock:
            self._streams = {key: entry for key, entry in self._streams.items() if entry[1] > now}
            subscribers = list(self._streams.values())
        if not subscribers:
            return
        snapshot = self.engine.snapshot()
        visible = {a["id"] for a in snapshot["watch_list"] if a["stream_enabled"]}
        payload = {"revision": snapshot["revision"], "feed_status": snapshot["feed_status"],
                   "live": {k: v for k, v in snapshot["live"].items() if k in visible},
                   "runtime": {k: v for k, v in snapshot["runtime"].items() if k in visible}}
        for content, expiry in subscribers:
            try:
                self._reply(content, payload, handler="crypto_alert.update")
            except Exception as exc:
                self.log(f"[CRYPTO] Stream callback failed: {type(exc).__name__}", level="WARNING")

    def worker_post(self):
        self.feed.stop()
        self.engine.stop()

    def shutdown_now(self, reason="normal"):
        self.running = False
        if hasattr(self, "engine"):
            self.worker_post()
        super().shutdown_now(reason)

    def send_simple_alert(self, message):
        endpoints = self.get_nodes_by_role(self._alert_role)
        if not endpoints:
            self.log("[CRYPTO] Alert delivery failed: no configured alert endpoint.", level="WARNING")
            return False
        delivered = False
        for endpoint in endpoints:
            try:
                notification = self.get_delivery_packet("notify.alert.general")
                notification.set_data({
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "universal_id": self.command_line_args["universal_id"],
                    "level": "warning", "msg": message,
                    "formatted_msg": f"Crypto Watch\n{message}",
                    "cause": "Crypto watch trigger", "origin": self.command_line_args["universal_id"],
                })
                packet = self.get_delivery_packet("standard.command.packet")
                packet.set_data({"handler": endpoint.get_handler()})
                packet.set_auto_fill_sub_packet(False)
                packet.set_packet(notification, "content")
                queued = self.pass_packet(packet, endpoint.get_universal_id())
                delivered = bool(queued) or delivered
            except Exception as exc:
                self.log(f"[CRYPTO] Alert delivery failed: {type(exc).__name__}", level="ERROR")
        return delivered


if __name__ == "__main__":
    Agent().boot()


