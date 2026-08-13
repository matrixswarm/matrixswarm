# Authored by Commander & ChatGPT — MatrixSwarm Email Egress Transport
# Gemini, Docstrings
# MATRIX_EMAIL_EGRESS — swarm-side SMTP egress only.
#
# Design:
#   - This agent is NOT a Phoenix reply agent.
#   - It exposes only swarm command handlers needed to route outbound payloads.
#   - Phoenix sends heartbeat over the email wire; this agent does not send heartbeats.
#   - Every outbound email-wire packet is stamped with:
#       session_id  -> Phoenix session this payload belongs to
#       ts          -> packet creation timestamp for stale cleanup on Phoenix IMAP side

import os
import sys

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

import base64
import uuid
import hashlib
import json
import smtplib
import imaplib
import email
import ssl
import time
import threading
from email.message import EmailMessage
from typing import Any, Optional
from Crypto.PublicKey import RSA
from core.python_core.utils.crypto_utils import (pem_fix, verify_signed_payload,)
from core.python_core.boot_agent import BootAgent
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from core.python_core.class_lib.packet_delivery.utility.security.unwrap_secure_packet import unwrap_secure_packet
from core.python_core.utils.crypto_utils import pem_fix
from core.python_core.class_lib.packet_delivery.utility.security.packet_security import wrap_packet_securely
from core.python_core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    """
    Swarm-side email egress agent for MatrixSwarm.

    Exposes command handlers to route outbound payloads over SMTP to designated
    Phoenix sessions and monitors IMAP heartbeats to manage active sessions.

    Allowed Swarm Interface:
        - cmd_send_alert_msg
        - cmd_status
        - cmd_toggle_perimeter
        - cmd_rpc_route
    """

    def __init__(self):
        """
        Initialize the Email Egress Agent instance.

        Parses configuration for SMTP payload and IMAP heartbeat lanes, initializes
        cryptographic signing keys, lockdown state, and computes local heartbeat identifiers.
        """
        super().__init__()

        try:
            self.AGENT_VERSION = "1.0.0"

            self._cfg_lock = threading.Lock()

            cfg = self.tree_node.get("config", {}) or {}
            email_cfg = cfg.get("email_egress", {}) or {}

            payload_lane = email_cfg["payload_lane"]
            heartbeat_lane = email_cfg["heartbeat_lane"]

            smtp_cfg = payload_lane["smtp"]
            heartbeat_imap_cfg = heartbeat_lane["imap"]

            required = [smtp_cfg["server"], smtp_cfg["port"], smtp_cfg["username"], smtp_cfg["password"],
                        smtp_cfg["to"]]

            if not all(required):
                raise RuntimeError("[EMAIL_EGRESS][BOOT_FAIL] payload_lane.smtp incomplete")

            self.hb_imap_server = heartbeat_imap_cfg["server"]
            self.hb_imap_port = int(heartbeat_imap_cfg["port"])
            self.hb_imap_user = heartbeat_imap_cfg["username"]
            self.hb_imap_pass = heartbeat_imap_cfg["password"]
            self.hb_imap_folder = heartbeat_imap_cfg.get("folder", "INBOX")

            self.encrypt_outgoing = bool(email_cfg.get("encrypt_outgoing", False) or cfg.get("encrypt_outgoing", False))
            self._sessions = {}  # phoenix_session_id -> {last_seen, ...}

            # Accept both old lane style and flatter connector-style config.
            payload_lane = email_cfg.get("payload_lane", {}) or {}
            smtp_cfg = (payload_lane.get("smtp", {}))

            self.lockdown_state = bool(cfg.get("lockdown_state", False))
            self.lockdown_time = int(cfg.get("lockdown_time", 0) or 0)
            self.lockdown_expires = 0

            self.smtp_server = smtp_cfg.get("server") or smtp_cfg.get("host") or smtp_cfg.get("smtp_server")
            self.smtp_port = int(smtp_cfg.get("port") or smtp_cfg.get("smtp_port") or 587)

            self.password = smtp_cfg.get("password") or smtp_cfg.get("smtp_password")
            self.from_address = smtp_cfg["username"]
            self.password = smtp_cfg["password"]
            self.to_address = smtp_cfg["to"]

            self.encryption = (smtp_cfg.get("encryption") or smtp_cfg.get("smtp_encryption") or "STARTTLS").upper().strip()
            self.subject_prefix = payload_lane.get("subject_prefix") or email_cfg.get("subject_prefix") or "MatrixSwarm Packet"

            self.poll_interval = int(payload_lane.get("poll_interval") or cfg.get("poll_interval") or 10)
            self.packet_ttl = int(payload_lane.get("packet_ttl") or cfg.get("packet_ttl") or 300)
            self.heartbeat_subject_prefix = heartbeat_lane.get("subject_prefix", "[MatrixSwarm-Heartbeat]")
            self.heartbeat_timeout_sec = int(heartbeat_lane.get("timeout_sec", 300))
            self.heartbeat_poll_timeout = max(3, min(8, int(self.poll_interval) - 1))

            # Signing material used for the outer email transport wrapper.
            signing_cfg = cfg.get("security", {}).get("signing", {}) or {}
            self.remote_pubkey = signing_cfg.get("remote_pubkey")
            self.local_privkey = signing_cfg.get("privkey")
            self._peer_pub_key_pem = pem_fix(self.remote_pubkey) if self.remote_pubkey else None
            self._signing_key_obj = RSA.import_key(pem_fix(self.local_privkey).encode()) if self.local_privkey else None

            self.last_sent_ts = 0
            self.last_sent_subject = None
            self.last_send_error = None
            self.sent_count = 0

            self._emit_beacon = self.check_for_thread_poke("worker", timeout=300, emit_to_file_interval=10)

            self._serial_num = self.tree_node.get('serial')
            self.heartbeat_packet_identifier = hashlib.sha256(f"{self._serial_num}email-egress-heartbeat".encode("utf-8")).hexdigest()
            self.log(f"[MATRIX_EMAIL_EGRESS][INIT][HEARTBEAT_PACKET_IDENTIFIER][{self.heartbeat_packet_identifier.upper()}]")

            if not self.smtp_server or not self.from_address or not self.to_address:
                self.log("[MATRIX_EMAIL_EGRESS][INIT][WARN] SMTP lane is incomplete.")
            if not self.remote_pubkey or not self.local_privkey:
                self.log("[MATRIX_EMAIL_EGRESS][INIT][WARN] Missing signing/encryption keys for email transport.")

        except Exception as e:
            self.log("[MATRIX_EMAIL_EGRESS][INIT][FATAL]", error=e)

    # ------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------
    def worker(self, config=None, identity: IdentityObject = None):
        """
        Main continuous worker loop execution step.

        Processes runtime live configuration updates, manages lockdown expiration timers,
        polls IMAP for incoming Phoenix heartbeats, and reaps stale session flag files.

        Args:
            config (dict, optional): Live configuration updates pushed to the worker.
            identity (IdentityObject, optional): Calling identity context.
        """
        try:
            if isinstance(config, dict) and bool(config.get("push_live_config", 0)):
                self._apply_live_config(config)

            if self.lockdown_state and self.lockdown_time > 0:
                now = int(time.time())
                if now >= self.lockdown_expires:
                    self.log("[LOCKDOWN] Time expired. Reopening perimeter.")
                    self.toggle_perimeter(False, 0)

            self._emit_beacon()
            self._poll_heartbeat_inbox()
            self._reap_dead_heartbeat_flags()

        except Exception as e:
            self.log("[MATRIX_EMAIL_EGRESS][WORKER][ERROR]", error=e)
        finally:
            interruptible_sleep(self, self.poll_interval)

    def _packet_dict(self, packet: Any) -> dict:
        """
        Extract and normalize a packet dictionary from an arbitrary packet object.

        Args:
            packet (Any): Raw packet instance or object with `get_packet()` method.

        Returns:
            dict: Extracted dictionary payload or empty dictionary if invalid.
        """
        if hasattr(packet, "get_packet"):
            try:
                packet = packet.get_packet()
            except Exception:
                packet = {}
        return packet if isinstance(packet, dict) else {}

    def _extract_session_id(self, packet: Any) -> Optional[str]:
        """
        Extract the target Phoenix session ID from a packet's metadata.

        Args:
            packet (Any): Incoming raw packet or dictionary.

        Returns:
            Optional[str]: Stripped session ID if found and non-empty, otherwise None.
        """
        packet = self._packet_dict(packet)
        sid = packet.get("session_id")
        if isinstance(sid, str) and sid.strip():
            return sid.strip()
        return None

    def _is_email_session_active(self, sid: str) -> bool:
        """
        Check if a given Phoenix session ID is active based on local file flag presence and TTL.

        Args:
            sid (str): Phoenix session identifier.

        Returns:
            bool: True if the session flag exists and has not expired, False otherwise.
        """
        if not sid:
            return False

        base = self._broadcast_dir()
        flag = os.path.join(base, f"connected.flag.{sid}")

        if not os.path.exists(flag):
            return False

        # enforce TTL
        try:
            age = time.time() - os.path.getmtime(flag)
            if age > self.heartbeat_timeout_sec:
                return False
        except Exception:
            return False

        return True

    def _secure_envelope(self, payload: dict, session_id: str) -> dict:
        """
        Sign and encrypt a payload object into a transport envelope for a Phoenix session.

        Args:
            payload (dict): Payload data to secure.
            session_id (str): Target session ID associated with the payload envelope.

        Returns:
            dict: Wrapped envelope dictionary containing signed content.

        Raises:
            ValueError: If payload is not a dict or session_id is missing.
            RuntimeError: If cryptographic signing keys or serial numbers are missing.
        """
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")
        if not session_id:
            raise ValueError("session_id is required for email egress")
        if not self._peer_pub_key_pem or not self._signing_key_obj:
            raise RuntimeError("email transport signing/encryption keys are not configured")
        if not self._serial_num:
            raise RuntimeError("email transport serial is not configured")

        recipient_hash = self._message_recipient_hash(session_id, self._serial_num)
        cleanup_hash = self._message_cleanup_hash(self._serial_num)

        now = int(time.time())
        signed_block = wrap_packet_securely(
            payload,
            peer_pub_key_pem=self._peer_pub_key_pem,
            signing_key_obj=self._signing_key_obj,
            extra_fields={
                "timestamp": now,
                "expires": now + self.packet_ttl,
                "hash": recipient_hash,
                "cleanup_hash": cleanup_hash,
            },
        )

        return {"content": signed_block}

    def _build_email(self, payload: dict, session_id: str, subject: Optional[str] = None) -> EmailMessage:
        """
        Construct a MIME EmailMessage instance wrapping the base64-encoded envelope.

        Args:
            payload (dict): Transport payload content.
            session_id (str): Recipient Phoenix session ID.
            subject (Optional[str]): Custom email subject line. Defaults to standard prefix.

        Returns:
            EmailMessage: Formatted email message object.

        Raises:
            ValueError: If the message recipient hash could not be generated.
        """
        envelope = self._secure_envelope(payload, session_id)
        payload_b64 = base64.b64encode(json.dumps(envelope, separators=(",", ":")).encode("utf-8")).decode("ascii")

        msg = EmailMessage()
        msg["From"] = self.from_address
        msg["To"] = self.to_address
        msg["Subject"] = subject or f"{self.subject_prefix}"
        msg.set_content(payload_b64)
        return msg

    def _smtp_send_message(self, msg: EmailMessage, timeout=20):
        """
        Transmit an EmailMessage over SMTP using configured security protocols.

        Args:
            msg (EmailMessage): Outbound email message.
            timeout (int): Socket timeout duration in seconds. Defaults to 20.

        Returns:
            dict: Dictionary of refused recipient addresses, if any.

        Raises:
            RuntimeError: If SMTP server configuration parameters are missing.
        """
        if not self.smtp_server or not self.from_address or not self.to_address:
            raise RuntimeError("SMTP lane is not configured")

        context = ssl.create_default_context()

        mode = (self.encryption or "STARTTLS").upper().strip()
        envelope_from = self.from_address
        envelope_to = [self.to_address]

        self.log(
            f"[EMAIL][SMTP][CONFIG] "
            f"server={self.smtp_server!r} port={self.smtp_port!r} mode={mode!r} "
            f"configured_from={self.from_address!r} "
            f"configured_to={self.to_address!r} "
            f"heartbeat_imap={self.hb_imap_user!r}"
        )
        self.log(
            f"[EMAIL][SMTP][HEADERS] "
            f"from={msg.get('From')!r} to={msg.get('To')!r} "
            f"reply_to={msg.get('Reply-To')!r} subject={msg.get('Subject')!r}"
        )
        self.log(
            f"[EMAIL][SMTP][ENVELOPE] "
            f"from={envelope_from!r} to={envelope_to!r}"
        )

        stage = "connect"
        try:
            if mode == "SSL":
                with smtplib.SMTP_SSL(
                        self.smtp_server,
                        self.smtp_port,
                        timeout=timeout,
                        context=context,
                ) as server:
                    self.log("[EMAIL][SMTP][CONNECT] SSL established")

                    if self.from_address and self.password:
                        stage = "login"
                        login_code, _ = server.login(self.from_address, self.password)
                        self.log(
                            f"[EMAIL][SMTP][LOGIN] user={self.from_address!r} "
                            f"code={login_code!r}"
                        )

                    stage = "send"
                    refused = server.send_message(
                        msg,
                        from_addr=envelope_from,
                        to_addrs=envelope_to,
                    )
            else:
                with smtplib.SMTP(
                        self.smtp_server,
                        self.smtp_port,
                        timeout=timeout,
                ) as server:
                    self.log("[EMAIL][SMTP][CONNECT] SMTP established")

                    if mode in ("TLS", "STARTTLS"):
                        stage = "starttls"
                        tls_code, _ = server.starttls(context=context)
                        self.log(
                            f"[EMAIL][SMTP][TLS] established code={tls_code!r}"
                        )

                    if self.from_address and self.password:
                        stage = "login"
                        login_code, _ = server.login(self.from_address, self.password)
                        self.log(
                            f"[EMAIL][SMTP][LOGIN] user={self.from_address!r} "
                            f"code={login_code!r}"
                        )

                    stage = "send"
                    refused = server.send_message(
                        msg,
                        from_addr=envelope_from,
                        to_addrs=envelope_to,
                    )

            if refused:
                self.log(f"[EMAIL][SMTP][REFUSED] recipients={refused!r}")
            else:
                self.log(
                    f"[EMAIL][SMTP][ACCEPTED] envelope_to={envelope_to!r}"
                )

            return refused

        except Exception as e:
            self.log(
                f"[EMAIL][SMTP][ERROR] stage={stage!r} "
                f"type={type(e).__name__} message={e}"
            )
            raise

    # ------------------------------------------------------------
    # Phoenix Heartbeat
    # ------------------------------------------------------------
    def _poll_heartbeat_inbox(self):
        """
        Poll IMAP mailbox for heartbeat messages, unwrap payloads, and update active sessions.
        """
        imap = None
        try:
            expected_hash = self.heartbeat_packet_identifier
            if not expected_hash:
                self.log("[HEARTBEAT][IMAP][DROP] Missing local heartbeat recipient hash.")
                return

            imap = imaplib.IMAP4_SSL(
                self.hb_imap_server,
                self.hb_imap_port,
                timeout=self.heartbeat_poll_timeout,
            )
            imap.login(self.hb_imap_user, self.hb_imap_pass)
            imap.select(self.hb_imap_folder)

            status, data = imap.uid("SEARCH", None, "UNDELETED")
            if status != "OK" or not data or not data[0]:
                return

            self.log(f"[HEARTBEAT][IMAP] found={len(data[0].split())} folder={self.hb_imap_folder}")

            for raw_id in data[0].split():
                msg_id = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)

                status, parts = imap.uid("FETCH", msg_id, "(UID FLAGS BODY.PEEK[])")
                if status != "OK":
                    continue

                raw_msg = self._extract_rfc822_bytes(parts)
                if raw_msg is None:
                    self.log(f"[HEARTBEAT][IMAP][READ_NO_BODY][LEAVE] uid={msg_id!r}")
                    continue

                msg = email.message_from_bytes(raw_msg)
                subject = str(msg.get("Subject", "")).strip()

                if not subject.startswith(self.heartbeat_subject_prefix):
                    continue

                body = self._extract_text_body(msg)
                #the heartbeat packet is a hash, which is public, but falls under the sig
                packet = self._decode_heartbeat_packet(body)
                if not packet:
                    self.log(f"[HEARTBEAT][IMAP][MALFORMED][LEAVE] uid={msg_id!r}")
                    continue

                if not self._verify_heartbeat_signature_only(packet):
                    continue

                packet_hash = self._extract_heartbeat_hash(packet)
                if packet_hash != expected_hash:
                    continue

                if self._is_stale_heartbeat_packet(packet):
                    self.log(f"[HEARTBEAT][IMAP][STALE][DELETE] uid={msg_id!r}")
                    imap.uid("STORE", msg_id, "+FLAGS.SILENT", r"(\Deleted)")
                    continue

                #decrypt and verify sig
                inner = unwrap_secure_packet(
                    packet,
                    remote_pubkey=self._peer_pub_key_pem or self.remote_pubkey,
                    local_privkey=self.local_privkey,
                    logger=self.log,
                )
                if not inner:
                    self.log(f"[HEARTBEAT][IMAP][UNWRAP_FAIL][DELETE] uid={msg_id!r}")
                    imap.uid("STORE", msg_id, "+FLAGS.SILENT", r"(\Deleted)")
                    continue

                session_id = self._extract_session_from_heartbeat_payload(inner)
                if not session_id:
                    self.log(f"[HEARTBEAT][IMAP][NO_SESSION][DELETE] uid={msg_id!r}")
                    imap.uid("STORE", msg_id, "+FLAGS.SILENT", r"(\Deleted)")
                    continue

                self._touch_session_flag(session_id)
                imap.uid("STORE", msg_id, "+FLAGS.SILENT", r"(\Deleted)")

            imap.expunge()

        except Exception as e:
            self.log("[HEARTBEAT][IMAP][ERROR]", error=e)

        finally:
            try:
                if imap:
                    imap.logout()
            except Exception:
                pass

    def _verify_heartbeat_signature_only(self, packet: Any) -> bool:
        try:
            if not isinstance(packet, dict):
                return False

            signed_block = packet.get("content")
            if not isinstance(signed_block, dict):
                return False

            signature = signed_block.get("sig")
            if not isinstance(signature, str) or not signature.strip():
                return False

            public_key = self._peer_pub_key_pem or self.remote_pubkey
            if isinstance(public_key, str):
                public_key = RSA.import_key(pem_fix(public_key).encode("utf-8"))

            verify_signed_payload(
                {k: v for k, v in signed_block.items() if k != "sig"},
                signature,
                public_key,
            )
            return True

        except Exception as e:
            self.log(
                f"[HEARTBEAT][BAD_SIG][LEAVE] "
                f"{type(e).__name__}: {e}"
            )
            return False


    def _resolve_agent_serial(self, cfg: Optional[dict] = None) -> Optional[str]:
        """
        Resolve agent serial string from instance attributes or configuration.

        Args:
            cfg (Optional[dict]): Candidate configuration dictionary.

        Returns:
            Optional[str]: Validated serial string if resolved, else None.
        """
        cfg = cfg or {}
        candidates = [
            getattr(self, "serial", None),
            cfg.get("serial"),
            self.tree_node.get("serial") if isinstance(self.tree_node, dict) else None,
        ]

        for serial in candidates:
            if isinstance(serial, str) and serial.strip():
                return serial.strip()
        return None

    @staticmethod
    def _heartbeat_recipient_hash(serial: Optional[str]) -> Optional[str]:
        """
        Compute SHA-256 recipient hash for matching heartbeat payloads.

        Args:
            serial (Optional[str]): Agent serial string.

        Returns:
            Optional[str]: Hexadecimal SHA-256 digest string if serial is valid, else None.
        """
        if not isinstance(serial, str):
            return None

        serial = serial.strip()
        if not serial:
            return None

        return hashlib.sha256(f"{serial}email-egress-heartbeat".encode("utf-8")).hexdigest()

    @staticmethod
    def _message_recipient_hash(session_id: Optional[str], serial: Optional[str]) -> Optional[str]:
        """
        Compute SHA-256 recipient hash for session message routing.

        Args:
            session_id (Optional[str]): Recipient session ID.
            serial (Optional[str]): Agent serial identifier.

        Returns:
            Optional[str]: Computed SHA-256 hex digest or None if parameters are invalid.
        """
        if not isinstance(session_id, str):
            return None
        if not serial:
            return None

        session_id = session_id.strip()
        if not session_id:
            return None

        return hashlib.sha256(f"{serial}{session_id}email-egress-message".encode("utf-8")).hexdigest()

    def _message_cleanup_hash(self, serial):
        return hashlib.sha256(
            f"{serial}email-egress-message".encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _extract_heartbeat_hash(packet: Any) -> Optional[str]:
        if not isinstance(packet, dict):
            return None

        signed_wrapper = packet.get("content")
        if not isinstance(signed_wrapper, dict):
            return None

        value = signed_wrapper.get("hash")
        if isinstance(value, str) and value.strip():
            return value.strip()

        return None

    def _extract_session_from_heartbeat_payload(self, payload: Any) -> Optional[str]:
        """
        Extract target session ID from decrypted heartbeat inner payload.

        Args:
            payload (Any): Decrypted heartbeat payload.

        Returns:
            Optional[str]: Session ID string if found, else None.
        """
        if not isinstance(payload, dict):
            return None

        candidates = [
            payload.get("session_id"),
            (payload.get("heartbeat") or {}).get("session_id")
            if isinstance(payload.get("heartbeat"), dict)
            else None,
        ]

        for session_id in candidates:
            if isinstance(session_id, str) and session_id.strip():
                return session_id.strip()
        return None

    def _is_stale_heartbeat_packet(self, packet: Any) -> bool:
        """
        Evaluate if a given heartbeat packet has expired or exceeded threshold age.

        Args:
            packet (Any): Heartbeat dictionary object.

        Returns:
            bool: True if expired or stale, False otherwise.
        """
        if not isinstance(packet, dict):
            return True

        now = time.time()
        ts = self._extract_packet_timestamp(packet)
        expires = self._extract_packet_expires(packet)

        if expires is not None:
            return now > expires

        if ts is None:
            return True

        return (now - ts) > self.heartbeat_timeout_sec

    @staticmethod
    def _fetch_response_has_flag(parts: Any, flag: str) -> bool:
        """
        Determine if an IMAP FETCH response payload contains a specific system flag.

        Args:
            parts (Any): Structure returned by imaplib UID FETCH command.
            flag (str): Target IMAP flag name (e.g., "Seen").

        Returns:
            bool: True if flag exists in response metadata, False otherwise.
        """
        target = f"\\{flag}".upper()
        if not isinstance(parts, (list, tuple)):
            return False

        for response_part in parts:
            metadata = response_part[0] if isinstance(response_part, tuple) else response_part
            if isinstance(metadata, bytes):
                metadata = metadata.decode("utf-8", errors="ignore")
            if isinstance(metadata, str) and target in metadata.upper():
                return True

        return False

    @staticmethod
    def _extract_packet_timestamp(packet: dict) -> Optional[float]:
        signed_block = packet.get("content")
        if not isinstance(signed_block, dict):
            return None

        for key in ("timestamp", "ts"):
            try:
                value = signed_block.get(key)
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                continue

        return None

    @staticmethod
    def _extract_packet_expires(packet: dict) -> Optional[float]:
        signed_block = packet.get("content")
        if not isinstance(signed_block, dict):
            return None

        try:
            value = signed_block.get("expires")
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _decode_heartbeat_packet(self, body: Optional[str]) -> Optional[dict]:
        """
        Decode string body into dictionary via base64 decoding or raw JSON parsing.

        Args:
            body (Optional[str]): Message body text.

        Returns:
            Optional[dict]: Parsed heartbeat packet dictionary or None if decoding fails.
        """
        body = (body or "").strip()
        if not body:
            return None

        try:
            decoded = base64.b64decode(body, validate=False).decode("utf-8")
            packet = json.loads(decoded)
            if isinstance(packet, dict):
                return packet
        except Exception:
            pass

        try:
            packet = json.loads(body)
            if isinstance(packet, dict):
                return packet
        except Exception:
            pass

        return None

    @staticmethod
    def _extract_rfc822_bytes(parts: Any) -> Optional[bytes]:
        """
        Extract raw message bytes from IMAP FETCH response structures.

        Args:
            parts (Any): Parts response list returned by imaplib.

        Returns:
            Optional[bytes]: Raw email payload bytes if present, else None.
        """
        if not isinstance(parts, (list, tuple)):
            return None

        for response_part in parts:
            if not isinstance(response_part, tuple) or len(response_part) < 2:
                continue

            raw_msg = response_part[1]
            if isinstance(raw_msg, bytearray):
                raw_msg = bytes(raw_msg)
            if isinstance(raw_msg, bytes):
                return raw_msg
        return None

    @staticmethod
    def _decode_text_payload(payload: Any, charset: Optional[str]) -> Optional[str]:
        """
        Decode raw payload byte sequence to string using specified encoding character set.

        Args:
            payload (Any): Raw input payload.
            charset (Optional[str]): Target charset name. Defaults to utf-8 if unspecified.

        Returns:
            Optional[str]: Decoded string representation or None if invalid type.
        """
        if isinstance(payload, bytearray):
            payload = bytes(payload)
        if isinstance(payload, bytes):
            return payload.decode(charset or "utf-8", errors="ignore")
        if isinstance(payload, str):
            return payload
        return None

    def _extract_text_body(self, msg):
        """
        Extract plain text content from a parsed EmailMessage object.

        Args:
            msg (EmailMessage): Parsed email message instance.

        Returns:
            Optional[str]: Plain text body string if extracted, else None.
        """
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disp = str(part.get("Content-Disposition", ""))
                if content_type == "text/plain" and "attachment" not in disp:
                    body = self._decode_text_payload(
                        part.get_payload(decode=True),
                        part.get_content_charset(),
                    )
                    if body is not None:
                        return body
        else:
            body = self._decode_text_payload(
                msg.get_payload(decode=True),
                msg.get_content_charset(),
            )
            if body is not None:
                return body
        return None

    def _broadcast_dir(self):
        """
        Resolve and ensure the directory path used for session broadcast flags exists.

        Returns:
            str: Directory path string for flag storage.
        """
        uid = self.command_line_args.get("universal_id")
        base = os.path.join(self.path_resolution["comm_path"], uid, "broadcast")
        os.makedirs(base, exist_ok=True)
        return base

    def _touch_session_flag(self, session_id: str):
        """
        Update in-memory session metadata and update the file modification timestamp flag.

        Args:
            session_id (str): Target session identifier.
        """
        now = int(time.time())

        # in-memory sessions (still useful for fan-out decisions)
        self._sessions[session_id] = {"last_seen": now, "source": "heartbeat"}

        # ONE TRUE FLAG: comm_path/<uid>/broadcast/connected.flag.<sid>
        flag = os.path.join(self._broadcast_dir(), f"connected.flag.{session_id}")
        with open(flag, "w", encoding="utf-8") as f:
            f.write("")  # mtime is the truth

        self.log(f"[HEARTBEAT] ✅ session open: {session_id}")

    def _reap_dead_heartbeat_flags(self):
        """
        Delete file flags and clear memory records for sessions exceeding heartbeat TTL.
        """
        now = time.time()
        base = self._broadcast_dir()

        for fname in os.listdir(base):
            if not fname.startswith("connected.flag."):
                continue

            sid = fname.replace("connected.flag.", "", 1).strip()
            path = os.path.join(base, fname)

            try:
                age = now - os.path.getmtime(path)
                if age > self.heartbeat_timeout_sec:
                    os.remove(path)
                    self._sessions.pop(sid, None)
                    self.log(f"[HEARTBEAT] 🪦 stale flag removed: {fname}")
            except Exception:
                pass

    def cmd_status(self, content, packet, identity: IdentityObject = None):
        """
        Swarm command handler returning status, agent settings, and egress performance metrics.

        Args:
            content (dict): Command content payload containing optional return parameters.
            packet (dict): Raw incoming packet metadata.
            identity (IdentityObject, optional): Caller identity object.
        """
        try:
            content = content or {}
            payload = {
                "lockdown_state": "Lockdown" if self.lockdown_state else "Open",
                "lockdown_time": self.lockdown_time,
                "lockdown_expires": str(bool(self.lockdown_expires)),
                "smtp_host": self.smtp_server,
                "smtp_user": self.from_address,
                "smtp_to": self.to_address,
                "poll_interval": self.poll_interval,
                "last_sent_ts": self.last_sent_ts,
                "last_sent_subject": self.last_sent_subject,
                "last_send_error": self.last_send_error,
                "sent_count": self.sent_count,
                "egress_mode": "smtp.email_wire.session_scoped",
            }

            return_handler = content.get("return_handler")
            if return_handler:
                self.crypto_reply(
                    response_handler=return_handler,
                    payload=payload,
                    session_id=content.get("session_id"),
                    token=content.get("token"),
                    rpc_role=self.tree_node.get("config", {}).get("rpc_router_role", "hive.rpc"),
                )
            else:
                self.log(f"[EMAIL][STATUS] {json.dumps(payload, sort_keys=True)}")

        except Exception as e:
            self.log("[EMAIL][STATUS][ERROR]", error=e, level="ERROR")

    def cmd_toggle_perimeter(self, content, packet, identity: IdentityObject = None):
        """
        Swarm command handler toggling perimeter lockdown state and timer expiration.

        Args:
            content (dict): Command configuration payload containing lockdown parameters.
            packet (dict): Incoming packet metadata.
            identity (IdentityObject, optional): Calling identity context.
        """
        try:
            content = content or {}
            lockdown_state = bool(content.get("lockdown_state", True))
            lockdown_time = int(content.get("lockdown_time", 0) or 0)

            self.toggle_perimeter(lockdown_state, lockdown_time)

            payload = {
                "lockdown_state": "Lockdown" if self.lockdown_state else "Open",
                "lockdown_time": self.lockdown_time,
                "lockdown_expires": str(bool(self.lockdown_expires)),
            }

            return_handler = content.get("return_handler")
            if return_handler:
                self.crypto_reply(
                    response_handler=return_handler,
                    payload=payload,
                    session_id=content.get("session_id"),
                    token=content.get("token"),
                    rpc_role=self.tree_node.get("config", {}).get("rpc_router_role", "hive.rpc"),
                )

            self.log(f"[LOCKDOWN] Perimeter toggled → {payload}")

        except Exception as e:
            self.log(f"[LOCKDOWN][ERROR] cmd_toggle_perimeter failed: {e}", error=e)

    # ------------------------------------------------------------
    # Perimeter + config
    # ------------------------------------------------------------
    def toggle_perimeter(self, lockdown_state, lockdown_time):
        """
        Update local perimeter lockdown state and calculate expiration timestamp.

        Args:
            lockdown_state (bool): Desired lockdown state flag.
            lockdown_time (int): Lockdown duration in seconds.
        """
        self.lockdown_time = int(lockdown_time or 0)
        if not bool(lockdown_state):
            self.lockdown_state = False
            self.lockdown_expires = 0
            self.log("[MATRIX_EMAIL_EGRESS] Packet Processing Turned On.")
        else:
            self.lockdown_state = True
            self.lockdown_expires = int(time.time()) + self.lockdown_time if self.lockdown_time > 0 else 0
            expires = self.lockdown_expires if self.lockdown_expires else "Never"
            self.log(f"[MATRIX_EMAIL_EGRESS] Packet Processing Turned Off. Expires: {expires}.")

    def _apply_live_config(self, cfg: dict):
        """
        Thread-safe application of configuration updates received at runtime.

        Args:
            cfg (dict): Dynamic configuration dictionary containing updated settings.
        """
        try:
            with self._cfg_lock:
                if "poll_interval" in cfg:
                    self.poll_interval = int(cfg.get("poll_interval", self.poll_interval))
                if "packet_ttl" in cfg:
                    self.packet_ttl = int(cfg.get("packet_ttl", self.packet_ttl))
        except Exception as e:
            self.log("[ORACLE][ERROR] Failed to apply live config", error=e)

    # -------------------------------
    # routing helpers
    # -------------------------------
    def _get_active_session_ids(self):
        """
        Gather active Phoenix session IDs across memory registers and flag directory.

        Returns:
            list[str]: Sorted list of unique active session ID strings.
        """
        session_ids = set(self._sessions.keys())

        try:
            base = self._broadcast_dir()
            for fname in os.listdir(base):
                if fname.startswith("connected.flag."):
                    sid = fname.replace("connected.flag.", "", 1).strip()
                    if sid:
                        session_ids.add(sid)
        except Exception:
            pass

        return sorted(session_ids)

    def _send(self, payload: dict, session_id: str):
        """
        Build and send an email packet to a specified target session.

        Args:
            payload (dict): Packet contents.
            session_id (str): Recipient Phoenix session identifier.

        Returns:
            bool: True if email transmitted successfully, False otherwise.
        """
        try:
            if not payload or not session_id:
                return False

            msg = self._build_email(payload, session_id)
            self._smtp_send_message(msg)

            self.log(f"[EMAIL][SEND] → {session_id}")
            return True

        except Exception as e:
            self.log("[EMAIL][SEND][ERROR]", error=e)
            return False

    def _route(self, payload: dict, session_id: str = None):
        """
        Route payload to a specified session or fan-out across all active sessions.

        Args:
            payload (dict): Payload content dictionary.
            session_id (str, optional): Target session ID or wildcard '*' for broadcast.

        Returns:
            bool: True if payload was successfully dispatched to at least one session.
        """
        self.log(f"[EMAIL][ROUTE] target={session_id or 'broadcast'}")
        if session_id and session_id != "*":
            if self._is_email_session_active(session_id):
                return self._send(payload, session_id)
            return False

        sent = False
        for sid in self._get_active_session_ids():
            if self._is_email_session_active(sid):
                self._send(payload, sid)
                sent = True

        return sent

    def cmd_send_alert_msg(self, content, packet, identity: IdentityObject = None):
        """
        Swarm command handler formatting alert messages for broadcast to active GUI clients.

        Args:
            content (dict): Alert message details (e.g., `msg`, `level`).
            packet (dict): Packet metadata.
            identity (IdentityObject, optional): Sender identity context.
        """
        try:
            if self.encryption_enabled and identity and identity.has_verified_identity():
                sender = identity.get_sender_uid()
            else:
                sender = packet.get("origin", "not specified")

            # Format the alert message
            msg = content.get("formatted_msg") or content.get("msg") or "[SWARM] Alert received."

            # Construct GUI-style feed packet
            broadcast_packet = {
                "handler": "swarm_feed.alert",
                "content": {
                    "origin": sender,
                    "timestamp": time.time(),
                    "id": uuid.uuid4().hex,
                    "formatted_msg": msg,
                    "level": content.get("level", "info")
                }
            }

            # Dispatch to all active sessions via Email
            self._route(self._secure_payload(broadcast_packet), "*")

            self.log("Alert message sent to GUI feed.")
        except Exception as e:
            self.log(error=e)

    def cmd_rpc_route(self, content, packet, identity: IdentityObject = None):
        """
        Swarm command handler routing RPC packets to target session over email transport.

        Args:
            content (dict): RPC invocation payload.
            packet (dict): Wrapper packet containing routing headers.
            identity (IdentityObject, optional): Verified identity of caller.
        """
        try:
            if not isinstance(content, dict):
                return

            packet = self._packet_dict(packet)
            session_id = self._extract_session_id(packet)

            if identity and identity.has_verified_identity():
                sender = identity.get_sender_uid()
            else:
                sender = packet.get("origin", "not specified")

            if self.lockdown_state:
                self.log(f"[MATRIX_EMAIL_EGRESS][BLOCKED] Packet Processing is Off. Access attempt from {sender}.")
                return

            if session_id:
                if self.debug.is_enabled():
                    self.log(f"[EMAIL][ROUTER] Directing to session {session_id} : Sender: {sender}")
                sent = self._route(content, session_id)
                if not sent:
                    self.log(
                        f"[EMAIL][ROUTER][DISPOSED] Session '{session_id}' not found or inactive — disposing: Sender: {sender}")
            else:
                self.log(f"[EMAIL][ROUTER] No session_id — broadcasting to all: Sender: {sender}.")
                self._route(content, "*")

        except Exception as e:
            self.log("[EMAIL][RPC][ERROR]", error=e)

    def _secure_payload(self, payload: dict) -> dict:
        """
        Create the inner packet consumed by Phoenix inbound_dispatcher.

        The serial is required here because inbound_dispatcher uses it to locate
        the sender's verification/decryption credentials in the vault.
        """
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")

        serial = self._serial_num
        if not isinstance(serial, str) or not serial.strip():
            raise RuntimeError("dispatcher packet serial is not configured")

        try:
            return wrap_packet_securely(
                payload,
                peer_pub_key_pem=self._peer_pub_key_pem,
                serial_num=serial.strip(),  # Required on INNER packet
                signing_key_obj=self._signing_key_obj,
                logger=self.log,
            )

        except Exception as e:
            self.log(
                "[EMAIL][SECURE_PAYLOAD][ERROR] "
                "Failed to build dispatcher packet",
                error=e,
            )
            raise

    def post_boot(self):
        """
        Post-boot operational hook logging agent initialization state.
        """
        self.log(
            f"[MATRIX_EMAIL_EGRESS] Version {self.AGENT_VERSION} — SMTP egress online. "
            f"Heartbeat IMAP monitor=on"
        )

if __name__ == "__main__":
    agent = Agent()
    agent.boot()