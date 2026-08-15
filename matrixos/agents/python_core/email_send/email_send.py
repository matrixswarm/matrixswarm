# Authored by Daniel F MacDonald and ChatGPT aka The Generals
import base64
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

from Crypto.PublicKey import RSA

from agents.python_core.email_send.factory.email_queue_manager import EmailQueueManager
from core.python_core.boot_agent import BootAgent
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from core.python_core.class_lib.packet_delivery.utility.security.packet_security import wrap_packet_securely
from core.python_core.class_lib.processes.thread_launcher import ThreadLauncher
from core.python_core.utils.crypto_utils import pem_fix


class Agent(BootAgent):
    """Relay swarm alerts to email, with optional signed payload encryption."""

    ENCRYPTED_ALERT_SUBJECT = "MatrixSwarm Encrypted Alert"
    ENCRYPTED_ALERT_MARKER = "MATRIXSWARM-ENCRYPTED-ALERT-V1"

    def __init__(self):
        super().__init__()
        self.thread_launcher = None
        self.queue = None
        self._peer_pub_key_pem = None
        self._signing_key_obj = None
        self._serial_num = self.tree_node.get("serial")

        try:
            cfg = self.tree_node.get("config", {}) or {}
            smtp = cfg.get("smtp", {}) or cfg.get("mail", {})

            self.smtp_server = smtp.get("smtp_server")
            self.smtp_port = smtp.get("smtp_port")
            self.from_address = smtp.get("smtp_username")
            self.password = smtp.get("smtp_password")
            self.to_address = smtp.get("smtp_to")
            self.encryption = (smtp.get("smtp_encryption") or "SSL").upper().strip()
            self.packet_ttl = int(
                smtp.get("packet_ttl") or cfg.get("packet_ttl") or 3600
            )

            # This switch protects the message inside the already encrypted SMTP
            # connection. It intentionally applies only to swarm alerts; the
            # explicit send_email service keeps its caller-supplied message.
            self.encrypt_alerts = bool(cfg.get("encrypt_alerts", False))
            self._configure_alert_security(cfg)

            state = "on" if self.encrypt_alerts else "off"
            self.log(f"Alert message encryption: {state}", level="INFO")
            self.email_message_send_packet_identifier = hashlib.sha256(
                f"{self._serial_num}email-send-message".encode("utf-8")
            ).hexdigest()

            self.thread_launcher = ThreadLauncher(self.log)
            self.queue = EmailQueueManager(log=self.log, thread_launcher=self.thread_launcher)

        except Exception as e:
            self.log(error=e, level="ERROR")

    def _configure_alert_security(self, cfg: dict) -> None:
        """Load explicit packet-encryption material without weakening boot."""
        if not self.encrypt_alerts:
            return

        signing_cfg = cfg.get("security", {}).get("signing", {}) or {}
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
            # Keep the agent online so configuration can be repaired, but leave
            # key state empty. The send path below will then fail closed.
            self._peer_pub_key_pem = None
            self._signing_key_obj = None
            self.log(
                "[EMAIL][ALERT_ENCRYPTION][KEY_ERROR] Assigned keys could not be loaded.",
                error=e,
                level="ERROR",
            )

    def _email_queue_ready(self) -> bool:
        if self.queue is not None:
            return True
        self.log("[EMAIL] ❌ Email queue is not initialized.", level="ERROR")
        return False

    def _secure_payload(self, payload: dict) -> dict:
        """Sign and encrypt one alert payload using assigned packet keys."""
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
                "hash": self.email_message_send_packet_identifier,
            },
        )

    @staticmethod
    def _alert_sender(packet, identity: IdentityObject = None) -> str:
        if identity and identity.has_verified_identity():
            return str(identity.get_sender_uid())
        if isinstance(packet, dict):
            return str(packet.get("origin", "not specified"))
        return "not specified"

    def _encrypt_alert_email(
        self,
        *,
        subject: str,
        body: str,
        content: dict,
        packet,
        identity: IdentityObject = None,
    ) -> tuple[str, str]:
        """Return a generic subject and a versioned base64 secure envelope."""
        payload = {
            "handler": "email_send.alert",
            "content": {
                "subject": str(subject),
                "body": str(body),
                "origin": self._alert_sender(packet, identity),
                "level": str(content.get("level", "info")),
                "timestamp": time.time(),
            },
        }
        envelope = {"content": self._secure_payload(payload)}
        encoded = base64.b64encode(
            json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).decode("ascii")
        return self.ENCRYPTED_ALERT_SUBJECT, f"{self.ENCRYPTED_ALERT_MARKER}\n{encoded}"

    def cmd_send_email(self, content: dict, packet: dict, identity: IdentityObject = None):
        """Entry point when swarm sends an explicit 'send email' command."""
        try:
            if not self._email_queue_ready():
                return

            smtp_server = content.get("smtp_server") or self.smtp_server
            raw_port = content.get("smtp_port") or self.smtp_port or 465
            try:
                smtp_port = int(raw_port)
            except (ValueError, TypeError):
                smtp_port = 465

            from_addr = content.get("from") or self.from_address
            to_addr = content.get("to") or self.to_address
            subject = (content.get("subject") or "MatrixSwarm Email").strip()
            password = content.get("password") or self.password
            encryption = (content.get("smtp_encryption") or self.encryption).upper().strip()
            body = content.get("body", "")

            if not all([smtp_server, from_addr, password, to_addr]):
                self.log("[EMAIL] ❌ Missing required fields.", level="ERROR")
                return

            self.queue.enqueue({
                "smtp_server": smtp_server,
                "smtp_port": smtp_port,
                "encryption": encryption,
                "from_addr": from_addr,
                "to_addr": to_addr,
                "password": password,
                "subject": subject,
                "body": body,
            })

        except Exception as e:
            self.log("[EMAIL] ❌ Failed to dispatch email", error=e)

    def cmd_send_alert_msg(self, content: dict, packet, identity: IdentityObject = None):
        """Format a swarm alert and enqueue plaintext or a secure envelope."""
        if not self._email_queue_ready():
            return

        if not all([self.smtp_server, self.smtp_port, self.from_address, self.password, self.to_address]):
            self.log("SMTP configuration is incomplete. Cannot send email.", level="ERROR")
            return

        try:
            subject = content.get("cause", "MatrixSwarm Alert")
            body = content.get("formatted_msg") or content.get("msg") or "No message content provided."

            if self.encrypt_alerts:
                subject, body = self._encrypt_alert_email(
                    subject=subject,
                    body=body,
                    content=content,
                    packet=packet,
                    identity=identity,
                )

            self.queue.enqueue({
                "agent": self,
                "smtp_server": self.smtp_server,
                "smtp_port": self.smtp_port,
                "encryption": self.encryption,
                "from_addr": self.from_address,
                "to_addr": self.to_address,
                "password": self.password,
                "subject": subject,
                "body": body,
            })

        except Exception as e:
            # Encryption failures must never downgrade to a plaintext alert.
            self.log(
                "[EMAIL][ALERT_ENCRYPTION][SEND_BLOCKED] Alert was not queued.",
                error=e,
                level="ERROR",
            )


if __name__ == "__main__":
    agent = Agent()
    agent.boot()
