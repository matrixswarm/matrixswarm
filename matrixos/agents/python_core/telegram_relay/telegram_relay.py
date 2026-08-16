# Authored by Daniel F MacDonald and ChatGPT aka The Generals
import base64
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

import requests
from Crypto.PublicKey import RSA

from core.python_core.boot_agent import BootAgent
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from core.python_core.class_lib.packet_delivery.utility.security.packet_security import wrap_packet_securely
from core.python_core.utils.crypto_utils import pem_fix
from core.python_core.utils.swarm_sleep import interruptible_sleep


class Agent(BootAgent):
    """Relay swarm alerts to Telegram with optional signed payload encryption."""

    ENCRYPTED_ALERT_MARKER = "MATRIXSWARM-ENCRYPTED-ALERT-V1"

    def __init__(self):
        super().__init__()

        config = self.tree_node.get("config", {}) or {}
        telegram = config.get("telegram", {}) or config

        self.token = telegram.get("bot_token")
        self.chat_id = telegram.get("chat_id")
        self.alerts_enabled = bool(config.get("alerts_enabled", True))
        self.encrypt_alerts = bool(config.get("encrypt_alerts", False))
        self.packet_ttl = int(config.get("packet_ttl") or 3600)
        self._serial_num = self.tree_node.get("serial")
        self._peer_pub_key_pem = None
        self._signing_key_obj = None
        self._configure_alert_security(config)

        self.telegram_message_send_packet_identifier = hashlib.sha256(
            f"{self._serial_num}telegram-relay-message".encode("utf-8")
        ).hexdigest()

        self.comm_folder = config.get("watch_comm", "mailman-1")
        path = os.path.join(self.path_resolution["comm_path_resolved"], "outgoing")
        os.makedirs(path, exist_ok=True)
        self.watch_path = os.path.join(self.path_resolution["comm_path_resolved"], "incoming")
        os.makedirs(self.watch_path, exist_ok=True)
        self._emit_beacon = self.check_for_thread_poke("worker", timeout=60, emit_to_file_interval=10)

        alert_state = "on" if self.alerts_enabled else "off"
        encryption_state = "on" if self.encrypt_alerts else "off"
        self.log(f"Alert delivery: {alert_state}", level="INFO")
        self.log(f"Alert message encryption: {encryption_state}", level="INFO")

    def _configure_alert_security(self, config: dict) -> None:
        """Load assigned signing/encryption material without weakening boot."""
        if not self.encrypt_alerts:
            return

        signing_cfg = config.get("security", {}).get("signing", {}) or {}
        remote_pubkey = signing_cfg.get("remote_pubkey")
        local_privkey = signing_cfg.get("privkey")

        try:
            self._peer_pub_key_pem = pem_fix(remote_pubkey) if remote_pubkey else None
            self._signing_key_obj = (
                RSA.import_key(pem_fix(local_privkey).encode("utf-8"))
                if local_privkey
                else None
            )
        except Exception as e:
            self._peer_pub_key_pem = None
            self._signing_key_obj = None
            self.log(
                "[TELEGRAM][ALERT_ENCRYPTION][KEY_ERROR] Assigned keys could not be loaded.",
                error=e,
                level="ERROR",
            )

    def _secure_payload(self, payload: dict) -> dict:
        """Sign and encrypt one alert payload using the assigned packet keys."""
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        if not self._peer_pub_key_pem or not self._signing_key_obj:
            raise RuntimeError("alert signing/encryption keys are not configured")

        serial = self._serial_num
        if not isinstance(serial, str) or not serial.strip():
            raise RuntimeError("alert packet serial is not configured")

        now = int(time.time())
        return wrap_packet_securely(
            payload,
            peer_pub_key_pem=self._peer_pub_key_pem,
            serial_num=serial.strip(),
            signing_key_obj=self._signing_key_obj,
            logger=self.log,
            extra_fields={
                "expires": now + self.packet_ttl,
                "hash": self.telegram_message_send_packet_identifier,
            },
        )

    @staticmethod
    def _alert_sender(packet, identity: IdentityObject = None) -> str:
        if identity and identity.has_verified_identity():
            return str(identity.get_sender_uid())
        if isinstance(packet, dict):
            return str(packet.get("origin", "not specified"))
        return "not specified"

    def _encrypt_alert_message(
        self,
        *,
        message: str,
        content: dict,
        packet,
        identity: IdentityObject = None,
    ) -> str:
        """Return a versioned base64 secure envelope with no alert plaintext."""
        payload = {
            "handler": "telegram_relay.alert",
            "content": {
                "message": str(message),
                "origin": self._alert_sender(packet, identity),
                "level": str(content.get("level", "info")),
                "timestamp": time.time(),
            },
        }
        envelope = {"content": self._secure_payload(payload)}
        encoded = base64.b64encode(
            json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).decode("ascii")
        return f"{self.ENCRYPTED_ALERT_MARKER}\n{encoded}"

    def worker_pre(self):
        self.log("[TELEGRAM] Telegram relay activated. Awaiting message drops...")

    def worker(self, config: dict = None, identity: IdentityObject = None):
        self._emit_beacon()  # patrol beacon
        interruptible_sleep(self, 20)

    def worker_post(self):
        self.log("[TELEGRAM] Relay shutting down. No more echoes for now.")

    def cmd_send_alert_msg(self, content, packet, identity:IdentityObject = None):
        if not self.alerts_enabled:
            self.log("[TELEGRAM] Alert delivery is disabled.", level="INFO")
            return

        try:
            message = self.format_message(content)
            if self.encrypt_alerts:
                message = self._encrypt_alert_message(
                    message=message,
                    content=content,
                    packet=packet,
                    identity=identity,
                )

            if self.send_to_telegram(message):
                self.log("[TELEGRAM] Message relayed successfully.")
        except Exception as e:
            self.log(
                "[TELEGRAM][ALERT_ENCRYPTION][SEND_BLOCKED] Alert was not sent.",
                error=e,
                level="ERROR",
            )

    def format_message(self, data: dict):
        """Builds a detailed message from embed_data if present."""
        embed = data.get("embed_data")
        if embed:
            # Construct a detailed message from the embed data
            title = embed.get('title', 'Swarm Alert')
            description = embed.get('description', 'No details.')
            footer = embed.get('footer', '')
            return f"*{title}*\n\n{description}\n\n_{footer}_"
        else:
            # Fallback for older alerts
            return data.get("formatted_msg") or data.get("msg") or "[SWARM] No content."

    def send_to_telegram(self, message):
        if not self.token or not self.chat_id:
            self.log("[TELEGRAM][ERROR] Missing bot_token or chat_id.")
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            resp = requests.post(url, json={"chat_id": self.chat_id, "text": message}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    self.log("[TELEGRAM] ✅ Message delivered successfully.")
                    return True
                else:
                    self.log(f"[TELEGRAM][ERROR] API error: {data}")
            else:
                body = resp.text.strip()
                if len(body) > 200:
                    body = body[:200] + "...[truncated]"
                self.log(f"[TELEGRAM][ERROR] HTTP {resp.status_code} → {body}")
        except Exception as e:
            self.log(f"[TELEGRAM][ERROR] Telegram delivery exception: {e}")
        return False

def on_alarm(self, payload):
    msg = f"🚨 [{payload['level'].upper()}] {payload['universal_id']} — {payload['cause']}"
    self.send_message_to_platform(msg)

if __name__ == "__main__":
    agent = Agent()
    agent.boot()
