# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import smtplib, ssl, json, base64, time, hashlib
from email.message import EmailMessage
from matrix_gui.core.class_lib.packet_delivery.utility.security.packet_security import wrap_packet_securely
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.modules.net.connector.interfaces.base_connector import BaseConnector
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.connector_bus import ConnectorBus

class SMTPConnector(BaseConnector):
    """
    Outbound one-shot email “catapult” connector.

    Implements the BaseConnector interface for sending Matrix packets via SMTP:
      - run_once(): performs a single email send mission and exits
      - send(): wraps, signs, encrypts, and dispatches the packet over SMTP
      - close(): emits a final disconnection event

    Attributes:
        proto (str): Protocol identifier ("smtp").
        smtp_host (str): SMTP server hostname.
        smtp_port (int): SMTP server port.
        smtp_user (str): Username for SMTP authentication.
        smtp_pass (str): Password for SMTP authentication.
        to_addr (str): Destination email address for packet delivery.
    """

    def __init__(self, shared=None):
        """
        Initialize the SMTPConnector, loading SMTP settings from shared context.

        Args:
            shared (dict, optional): Shared context including 'session_id',
                'agent', 'deployment', and 'packet'.
        """
        super().__init__(shared=shared)
        self.proto = "smtp"

        conn = self.agent.get("connection", {}) if self.agent else {}
        self.smtp_host = conn.get("smtp_server")
        self.smtp_port = conn.get("smtp_port")
        self.smtp_user = conn.get("smtp_username")
        self.smtp_pass = conn.get("smtp_password")
        self.to_addr   = conn.get("smtp_to")

        if not all([self.smtp_host, self.smtp_port, self.smtp_user, self.smtp_pass, self.to_addr]):
            print("[SMTPConnector] ⚠️ Incomplete SMTP configuration.")
            self._set_status("error")

    # ------------------------------------------------------------------
    # Single-mission run
    # ------------------------------------------------------------------
    def run_once(self):
        """
        Execute a single SMTP send mission then exit.

        Retrieves the packet from shared context, calls send(),
        and signals completion or error before closing.
        """
        try:
            print(f"[SMTPConnector] 🚀 Launching SMTP send for {self.agent.get('universal_id')}")

            packet = self._shared.get("packet")
            if not packet:
                print("[SMTPConnector] ❌ No packet found in shared context.")
                return

            self.send(packet)
            print("[SMTPConnector] ✅ Mission complete.")

        except Exception as e:
            print(f"[SMTPConnector][ERROR] {e}")

        finally:
            self.close(self.session_id, self.agent.get("universal_id"))

    @staticmethod
    def _recipient_hash(serial):
        """Return the signed mailbox-routing tag for a MATRIX_EMAIL agent."""
        if not isinstance(serial, str) or not serial.strip():
            return None
        return hashlib.sha256(
            f"{serial.strip()}matrix-email-ingress".encode("utf-8")
        ).hexdigest()

    # ------------------------------------------------------------------
    # Transmission
    # ------------------------------------------------------------------
    def send(self, packet: Packet, timeout=10):
        """
        Wrap, sign, encrypt, and send a Matrix packet via SMTP.

        Args:
            packet (Packet): The Matrix packet to transmit.
            timeout (int): Seconds to wait for SMTP operations.

        Behavior:
          1. Emit start event on ConnectorBus.
          2. Build inner payload with packet, timestamp, and session_id.
          3. Secure envelope via wrap_packet_securely (sign & encrypt).
          4. Base64-encode the JSON payload into email body.
          5. Connect to SMTP server over TLS, authenticate, and send.
          6. Emit end event on ConnectorBus.
        """
        ctx = get_sessions().get(self.session_id)
        if not ctx:
            print(f"[SMTPConnector] ❌ No session context for {self.session_id}")
            return

        if hasattr(ctx, "bus"):
            ctx.bus.emit("channel.packet.sent", start_end=1)

        try:
            target_serial = self.agent.get("serial") if isinstance(self.agent, dict) else None
            recipient_hash = self._recipient_hash(target_serial)
            if not recipient_hash:
                print("[SMTPConnector] ❌ Target MATRIX_EMAIL serial is required for signed mailbox routing.")
                return False

            # Wrap and encrypt payload
            inner = {
                "matrix_packet": packet.get_packet(),
                "ts": int(time.time()),
                "session_id": self.session_id,
            }
            envelope = wrap_packet_securely(
                inner,
                deployment=self.deployment,
                sign=True,
                encrypt=True,
                target_uid=self.agent.get("universal_id"),
                extra_fields={"hash": recipient_hash},
            )

            payload_b64 = base64.b64encode(
                json.dumps(envelope.get_packet()).encode()
            ).decode()

            self._emit_status("connected")

            msg = EmailMessage()
            msg["From"] = self.smtp_user
            msg["To"] = self.to_addr
            msg.set_content(payload_b64)

            # Secure connection
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=timeout) as server:
                server.starttls(context=context)
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)

            print(f"[SMTPConnector] 📧 Sent packet to {self.to_addr}")

        except Exception as e:
            print(f"[SMTPConnector] ❌ SMTP send error: {e}")

        finally:
            if hasattr(ctx, "bus"):
                ctx.bus.emit("channel.packet.sent", start_end=0)

    # ------------------------------------------------------------------
    # Close / telemetry
    # ------------------------------------------------------------------
    def close(self, session_id=None, channel_name=None):
        """
        Emit a disconnection event and update status to 'disconnected'.

        Args:
            session_id (str, optional): Session identifier for the event.
            channel_name (str, optional): Connector name (defaults to 'smtp').
        """

        self._emit_status("disconnected")