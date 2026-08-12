# Authored by Daniel F MacDonald and ChatGPT-5.3 aka The Generals
import base64
import email
import hashlib
import imaplib
import json
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Any, Optional
from Crypto.PublicKey import RSA
from matrix_gui.core.utils.crypto_utils import verify_signed_payload
from matrix_gui.core.connector_bus import ConnectorBus
from matrix_gui.core.class_lib.packet_delivery.utility.encryption.utility.unwrap_secure_packet import unwrap_secure_packet
from matrix_gui.core.class_lib.packet_delivery.utility.security.packet_security import wrap_packet_securely
from matrix_gui.modules.net.connector.interfaces.base_connector import BaseConnector
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log


class IMAPIngressConnector(BaseConnector):
    """
    Phoenix-side IMAP ingress connector.

    Responsibilities:
      1. Poll an IMAP mailbox for encrypted MatrixSwarm payloads.
      2. Unwrap valid payloads and emit them into Phoenix as inbound.raw.
      3. Periodically send a heartbeat over the configured SMTP heartbeat lane.

    Important:
      The heartbeat session_id MUST be Phoenix's live session_id, not the agent
      universal_id. Multiple Phoenix sessions can connect to the same deployment,
      so using the agent UID collapses independent sessions into one false flag.
    """

    def __init__(self, shared=None):
        super().__init__(shared=shared)
        self.shared = shared or {}

        conn = self.agent.get("connection", {}) if self.agent else {}

        # IMAP receive lane
        self.proto = "imap"
        self._imap = None
        self.poll_interval = int(conn.get("poll_interval", 10))
        self.folder = conn.get("imap_folder") or conn.get("folder", "INBOX")
        self.subject_prefix = conn.get("subject_prefix", "")
        self.from_filter = conn.get("from_filter", "")
        self.mark_seen_on_success_only = bool(conn.get("mark_seen_on_success_only", False))
        # Shared mailbox session routing. Packets older than this are globally deleted.
        self.max_packet_age_sec = int(conn.get("max_packet_age_sec", conn.get("packet_ttl", 300)))
        self.serial = self.agent.get("serial", None)

        # Phoenix session identity. This is the critical value the swarm side uses
        # to create/refresh connected.flag.email.<session_id>.
        self._phoenix_session_id = (
            self.session_id
            or self.shared.get("session_id")
            or self.shared.get("cockpit_id")
            or conn.get("session_id")
        )
        self.message_packet_identifier = self._message_recipient_hash(self._phoenix_session_id, self.serial)
        if not self.message_packet_identifier:
            print("[IMAP][INIT][WARN] Missing Phoenix session_id for message recipient hash.")

        # Heartbeat lane (Phoenix -> swarm email agent, via SMTP)
        hb_conn = conn.get("heartbeat_lane", {}) or {}
        hb_smtp = hb_conn.get("smtp", {}) or {}


        self.heartbeat_enabled = bool(hb_conn.get("enabled", True))
        self.heartbeat_interval = int(hb_conn.get("interval_sec", 120))
        self.heartbeat_interval = max(60, self.heartbeat_interval)
        self.heartbeat_subject_prefix = hb_conn.get("subject_prefix", "[MatrixSwarm-Heartbeat]")

        self._smtp_server = hb_smtp.get("server") or hb_smtp.get("host")
        self._smtp_port = int(hb_smtp.get("port", 587))
        self._smtp_user = hb_smtp.get("username") or hb_smtp.get("user")
        self._smtp_pass = hb_smtp.get("password") or hb_smtp.get("pass")
        self._smtp_to = hb_smtp.get("to") or hb_conn.get("to")
        self._smtp_from = hb_smtp.get("from") or self._smtp_user
        self._smtp_encryption = (hb_smtp.get("encryption") or "STARTTLS").upper().strip()

        self._last_heartbeat_sent = 0.0
        self._heartbeat_counter = 0

        self._channel_uid = self.agent.get("universal_id") if self.agent else "imap"

        print(f"[IMAP][INIT]{self._channel_uid} loaded!")


    # ------------------------------------------------------------------
    # Main persistent loop
    # ------------------------------------------------------------------
    def _wait_interruptibly(self, seconds):
        deadline = time.monotonic() + max(0.0, float(seconds))
        while not self.stopped():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            time.sleep(min(0.1, remaining))
        return False

    def loop_tick(self):
        try:
            if not self._phoenix_session_id:
                print("[IMAP][SESSION][WARN] Missing Phoenix session_id; heartbeat suppressed.")

            if not self._imap:
                self._connect_imap()
                if not self._imap:
                    self._emit_status("disconnected")
                    self._wait_interruptibly(5)
                    return not self.stopped()

            self._emit_status("connected")
            self._poll_mailbox()
            if self.stopped():
                return False
            self._maybe_send_heartbeat()
            return True

        except Exception as e:
            emit_gui_exception_log("[IMAPIngressConnector.loop_tick]", e)
            self._close_imap()
            self._emit_status("disconnected")
            self._wait_interruptibly(5)
            return not self.stopped()

    # ------------------------------------------------------------------
    # Heartbeat: Phoenix -> swarm email egress watchdog
    # ------------------------------------------------------------------
    def _maybe_send_heartbeat(self):
        if not self.heartbeat_enabled:
            return False

        now = time.time()
        if now - self._last_heartbeat_sent < self.heartbeat_interval:
            return False

        # throttle first so even partial/send-side weirdness cannot spam
        self._last_heartbeat_sent = now

        ok = self._send_heartbeat(now=now)
        return ok

    def _send_heartbeat(self, now=None):
        """
        Send a signed/encrypted heartbeat over SMTP.

        The swarm-side email agent receives this off the email wire, extracts
        content.session_id, touches connected.flag.<session_id>, then
        keeps refreshing it in 15 second intervals until this heartbeat stops.
        """
        try:
            if not self.heartbeat_enabled:
                return False

            if not self._phoenix_session_id:
                print("[IMAP][HEARTBEAT][DROP] Missing Phoenix session_id.")
                return False

            if not self._smtp_server or not self._smtp_to or not self._smtp_from:
                print("[IMAP][HEARTBEAT][DROP] Missing heartbeat SMTP lane fields.")
                return False

            now = now or time.time()
            self._heartbeat_counter += 1

            heartbeat_packet = {
                "type": "heartbeat",
                "session_id": self._phoenix_session_id,
                "ts": now,
                "status": "alive",
                "origin": "Phoenix.IMAPIngressConnector",
                "channel": self._channel_uid,
                "count": self._heartbeat_counter,
            }

            envelope = self._wrap_for_email_wire(heartbeat_packet)
            if envelope is None:
                print("[IMAP][HEARTBEAT][DROP] Could not sign/encrypt heartbeat.")
                return False

            sent = self._send_smtp_envelope(envelope)
            if sent:
                self.heartbeat()
                self._emit_status("heartbeat_sent")

            return sent

        except Exception as e:
            emit_gui_exception_log("[IMAPIngressConnector._send_heartbeat]", e)
            return False

    def _wrap_for_email_wire(self, heartbeat_packet: dict):
        """
        Wrap a heartbeat packet using the same Phoenix-side packet security path
        used for other email-wire packets.
        """
        try:
            if not self.deployment:
                print("[IMAP][WRAP] No deployment context available.")
                return None

            inner = {
                "heartbeat": heartbeat_packet,
                "ts": int(time.time()),
                "session_id": self._phoenix_session_id,
            }

            recipient_hash = self._heartbeat_recipient_hash(self.serial)
            if not recipient_hash:
                print("[IMAP][HEARTBEAT][DROP] Could not build heartbeat recipient hash.")
                return False

            target_uid = self._channel_uid
            return wrap_packet_securely(
                inner_data=inner,
                deployment=self.deployment,
                sign=True,
                encrypt=True,
                target_uid=target_uid,
                extra_fields={"hash": recipient_hash},
            )

        except Exception as e:
            emit_gui_exception_log("[IMAPIngressConnector._wrap_for_email_wire]", e)
            return None

    def _send_smtp_envelope(self, envelope: Any):
        try:
            payload_data = envelope.get_packet() if hasattr(envelope, "get_packet") else envelope
            if isinstance(payload_data, str):
                payload_data = json.loads(payload_data)

            if self.serial is None:
                print("imap._send_smtp_envelope No serial provided.")
                return False

            payload_b64 = base64.b64encode(
                json.dumps(payload_data, separators=(",", ":")).encode("utf-8")
            ).decode("ascii")

            msg = EmailMessage()
            msg["From"] = self._smtp_from
            msg["To"] = self._smtp_to
            msg["Subject"] = f"{self.heartbeat_subject_prefix}"
            msg.set_content(payload_b64)

            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

            if self._smtp_encryption == "SSL":
                with smtplib.SMTP_SSL(self._smtp_server, self._smtp_port, timeout=15, context=context) as smtp:
                    self._smtp_login_if_needed(smtp)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(self._smtp_server, self._smtp_port, timeout=15) as smtp:
                    if self._smtp_encryption in ("TLS", "STARTTLS"):
                        smtp.starttls(context=context)
                    self._smtp_login_if_needed(smtp)
                    smtp.send_message(msg)

            return True

        except Exception as e:
            emit_gui_exception_log("[IMAPIngressConnector._send_smtp_envelope]", e)
            return False

    @staticmethod
    def _heartbeat_recipient_hash(serial: Optional[str]) -> Optional[str]:
        if not isinstance(serial, str):
            return None

        serial = serial.strip()
        if not serial:
            return None

        return hashlib.sha256(f"{serial}email-egress-heartbeat".encode("utf-8")).hexdigest()

    def _smtp_login_if_needed(self, smtp):
        if self._smtp_user and self._smtp_pass:
            smtp.login(self._smtp_user, self._smtp_pass)

    # ------------------------------------------------------------------
    # IMAP receive lane
    # ------------------------------------------------------------------
    def _connect_imap(self):
        creds = self._resolve_imap_creds()
        if not creds:
            self._emit_status("disconnected")
            return

        try:
            self._imap = imaplib.IMAP4_SSL(creds["host"], creds["port"])
            self._imap.login(creds["username"], creds["password"])
            self._imap.select(creds.get("folder", self.folder or "INBOX"))
            self._emit_status("connected", creds["host"], creds["port"])
        except Exception as e:
            print(f"[IMAP][CONNECT] Failed to connect: {e}")
            self._close_imap()
            self._emit_status("disconnected")

    def _resolve_imap_creds(self):
        conn = self.agent.get("connection", {}) if self.agent else {}

        payload_lane = conn.get("payload_lane", {}) or {}
        imap_cfg = payload_lane.get("imap", {}) or {}

        host = imap_cfg.get("server")
        port = imap_cfg.get("port", 993)
        username = imap_cfg.get("username")
        password = imap_cfg.get("password")
        folder = imap_cfg.get("folder", self.folder or "INBOX")

        if not all([host, port, username, password]):
            print(f"[IMAP][CREDS][FAIL] connection keys={list(conn.keys())}")
            print(f"[IMAP][CREDS][FAIL] payload_lane keys={list(payload_lane.keys())}")
            print(f"[IMAP][CREDS][FAIL] imap keys={list(imap_cfg.keys())}")
            return None

        return {
            "host": host,
            "port": int(port),
            "username": username,
            "password": password,
            "folder": folder,
        }

    def _poll_mailbox(self):
        """
        Poll shared IMAP mailbox.

        Rules:
          - If recovered packet ts is stale, delete it from the mailbox globally.
          - If recovered packet session_id is not this Phoenix session, leave it
            unseen/unmodified so the correct session can process it.
          - If packet is for this session, emit inbound.raw and delete it.
        """
        if not self._imap:
            return

        try:
            status, data = self._imap.uid("SEARCH", None, "UNDELETED")
            if status != "OK" or not data or not data[0]:
                return

            remote_pubkey, local_privkey = self._get_transport_keys()
            if not remote_pubkey or not local_privkey:
                print("[IMAP][DROP] Missing outer transport keys for payload unwrap.")
                return
            expected_hash = self.message_packet_identifier or self._message_recipient_hash(self._phoenix_session_id, self.serial)
            if not expected_hash:
                print("[IMAP][DROP] Missing local message recipient hash.")
                return

            now = time.time()

            for msg_id in data[0].split():
                action = "leave"  # leave | seen | delete
                try:
                    status, parts = self._imap.uid("FETCH", msg_id, "(UID FLAGS BODY.PEEK[])")
                    if status != "OK" or not parts:
                        continue

                    # imaplib FETCH responses can contain both a tuple carrying
                    # RFC822 bytes and standalone response metadata (for
                    # example b")").  Indexing parts[0][1] is unsafe: if the
                    # first item is standalone bytes, it returns one integer.
                    raw_msg = self._extract_rfc822_bytes(parts)
                    if raw_msg is None:
                        if self._fetch_response_has_flag(parts, "Seen"):
                            print(f"[IMAP][FETCH][READ_NO_BODY][LEAVE] uid={msg_id!r}")
                        else:
                            print(f"[IMAP][FETCH][SKIP] No message payload in UID fetch response for {msg_id!r}")
                        continue

                    msg = email.message_from_bytes(raw_msg)
                    subj = str(msg.get("Subject", ""))

                    heartbeat_prefix = self.heartbeat_subject_prefix
                    is_heartbeat_subject = bool(
                        heartbeat_prefix and heartbeat_prefix in subj
                    )

                    # Apply the normal payload subject filter only to non-heartbeat mail.
                    if (
                            not is_heartbeat_subject
                            and self.subject_prefix
                            and self.subject_prefix not in subj
                    ):
                        continue

                    if self.from_filter:
                        sender = str(msg.get("From", ""))
                        if self.from_filter not in sender:
                            continue

                    body = self._extract_text_body(msg)
                    if not body:
                        continue

                    outer_packet = self._decode_outer_packet(body)
                    if not outer_packet:
                        continue

                    packet_hash = self._extract_message_hash(outer_packet)
                    packet_cleanup_hash = self._extract_cleanup_hash(outer_packet)

                    expected_cleanup_hash = hashlib.sha256(
                        f"{self.serial}email-egress-message".encode("utf-8")
                    ).hexdigest()

                    heartbeat_hash = self._heartbeat_recipient_hash(self.serial)

                    # Phoenix heartbeat: never verify it with the Swarm message key.
                    # Leave fresh heartbeats for MatrixSwarm; remove abandoned ones.
                    if packet_hash == heartbeat_hash:
                        if self._is_stale_outer_packet(outer_packet, now):
                            print(f"[IMAP][HEARTBEAT][STALE][DELETE] uid={msg_id!r}")
                            action = "delete"
                        else:
                            action = "leave"
                        continue

                    claims_current_session = packet_hash == expected_hash
                    claims_this_node = packet_cleanup_hash == expected_cleanup_hash

                    # Shared-inbox protection: never touch another node's packet.
                    if not claims_current_session and not claims_this_node:
                        action = "leave"
                        continue

                    # Verify exactly once. A failure claiming this node/session is junk.
                    if not self._verify_outer_signature_only(
                            outer_packet,
                            remote_pubkey,
                    ):
                        print(
                            f"[IMAP][BAD_SIG][DELETE] uid={msg_id!r} "
                            f"current_session={claims_current_session} "
                            f"this_node={claims_this_node}"
                        )
                        action = "delete"
                        continue

                    # Authenticated packet for another session belonging to this node.
                    # Preserve it while live; delete it after expiration.
                    if not claims_current_session:
                        if self._is_stale_outer_packet(outer_packet, now):
                            print(f"[IMAP][STALE_SESSION][DELETE] uid={msg_id!r}")
                            action = "delete"
                        else:
                            action = "leave"
                        continue

                    # Only delete Seen mail after signature and ownership checks.
                    if self._fetch_response_has_flag(parts, "Seen"):
                        print(f"[IMAP][READ][DELETE] uid={msg_id!r}")
                        action = "delete"
                        continue

                    # Verify again, enforce expiry, and decrypt the owned live packet.
                    inner = unwrap_secure_packet(
                        outer_packet,
                        remote_pubkey=remote_pubkey,
                        local_privkey=local_privkey,
                        logger=print,
                    )

                    if not inner:
                        print("[IMAP][DROP] Failed outer unwrap")
                        action = "delete"
                        continue

                    if not self._is_dispatcher_packet(inner):
                        print("[IMAP][DROP] Invalid dispatcher packet")
                        action = "delete"
                        continue

                    sid = self._phoenix_session_id

                    ConnectorBus.get(sid).emit(
                        "inbound.raw",
                        session_id=self.session_id,
                        channel=self._channel_uid,
                        source=self._channel_uid,
                        payload=inner,
                        ts=self._extract_outer_packet_ts(outer_packet) or now,
                    )
                    action = "delete"

                except Exception as e:
                    print(f"[IMAP][PARSE] Failed to process message {msg_id}: {e}")
                    action = "leave"

                finally:
                    try:
                        if action == "delete":
                            self._imap.uid("STORE", msg_id, "+FLAGS.SILENT", r"(\Deleted)")
                        elif action == "seen":
                            self._imap.uid("STORE", msg_id, "+FLAGS.SILENT", r"(\Seen)")
                        elif action == "leave" and not self.mark_seen_on_success_only:
                            # Commander note:
                            # In session-scoped mode we intentionally DO NOT mark
                            # unrelated session packets as Seen. This setting only
                            # applies to malformed/non-target messages when the
                            # operator explicitly wants mailbox draining behavior.
                            pass
                    except Exception:
                        pass

            try:
                # Expunge only after the loop so stale deletes are actually removed.
                self._imap.expunge()
            except Exception:
                pass

            self._wait_interruptibly(self.poll_interval)

        except Exception as e:
            emit_gui_exception_log("[IMAPIngressConnector._poll_mailbox]", e)
            self._close_imap()

    def _extract_cleanup_hash(self, outer_packet):
        try:
            value = outer_packet["content"].get("cleanup_hash")
            return value if isinstance(value, str) else None
        except (TypeError, KeyError):
            return None

    def _extract_session_and_ts(self, inner: Any):
        """
        Recover routing metadata from the signed email-wire envelope.

        unwrap_secure_packet verifies this signed block before the returned
        metadata is trusted by the receive loop.
        """
        session_id = None
        ts = None

        try:
            if isinstance(inner, dict):
                signed_block = inner.get("content")
                if isinstance(signed_block, dict):
                    session_id = signed_block.get("session_id")
                    ts = signed_block.get("ts") or signed_block.get("timestamp")

        except Exception:
            pass

        if isinstance(session_id, str):
            session_id = session_id.strip() or None

        try:
            ts = float(ts) if ts is not None else None
        except Exception:
            ts = None

        return session_id, ts

    def _is_dispatcher_packet(self, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False

        serial = payload.get("serial")
        sig = payload.get("sig")

        return (
            isinstance(serial, str)
            and bool(serial.strip())
            and isinstance(sig, str)
            and bool(sig.strip())
            and "content" in payload
        )

    @staticmethod
    def _message_recipient_hash(session_id: Optional[str], serial: Optional[str]) -> Optional[str]:
        if not isinstance(session_id, str):
            return None
        if not serial:
            return None

        session_id = session_id.strip()
        if not session_id:
            return None

        return hashlib.sha256(f"{serial}{session_id}email-egress-message".encode("utf-8")).hexdigest()

    @staticmethod
    def _extract_message_hash(packet: Any) -> Optional[str]:
        if not isinstance(packet, dict):
            return None

        signed_wrapper = packet.get("content")
        if not isinstance(signed_wrapper, dict):
            return None

        value = signed_wrapper.get("hash")
        if isinstance(value, str) and value.strip():
            return value.strip()

        return None

    def _is_stale_outer_packet(self, packet: Any, now: Optional[float] = None) -> bool:
        if not isinstance(packet, dict):
            return True

        now = now or time.time()
        expires = self._extract_outer_packet_expires(packet)
        if expires is not None:
            return now > expires

        ts = self._extract_outer_packet_ts(packet)
        if ts is None:
            return True

        return (now - ts) > self.max_packet_age_sec

    @staticmethod
    def _extract_outer_packet_ts(packet: dict) -> Optional[float]:
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
    def _extract_outer_packet_expires(packet: dict) -> Optional[float]:
        signed_block = packet.get("content")
        if not isinstance(signed_block, dict):
            return None

        try:
            value = signed_block.get("expires")
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _verify_outer_signature_only(self, outer_packet: Any, remote_pubkey,) -> bool:
        """
        Verify the email-wire signature without enforcing expiry,
        replay protection, recipient ownership, or decrypting content.

        This permits authenticated stale packets belonging to dead
        Phoenix sessions to be deleted safely.
        """
        try:
            if not isinstance(outer_packet, dict):
                return False

            # Email envelope shape:
            # {
            #     "content": {
            #         "content": <encrypted payload>,
            #         "timestamp": ...,
            #         "expires": ...,
            #         "session_id": ...,
            #         "hash": ...,
            #         "sig": ...
            #     }
            # }
            signed_wrapper = outer_packet.get("content")
            if not isinstance(signed_wrapper, dict):
                print("[IMAP][BAD_SIG] Signed wrapper is missing.")
                return False

            signature = signed_wrapper.get("sig")
            if not isinstance(signature, str) or not signature.strip():
                print("[IMAP][BAD_SIG] Signature is missing.")
                return False

            if isinstance(remote_pubkey, str):
                public_key_obj = RSA.import_key(remote_pubkey.encode("utf-8"))
            else:
                public_key_obj = remote_pubkey

            # Every wrapper field except sig is verified—including:
            # content, serial, timestamp, expires, session_id, and hash.
            payload_to_verify = {
                key: value
                for key, value in signed_wrapper.items()
                if key != "sig"
            }

            verify_signed_payload(
                payload_to_verify,
                signature,
                public_key_obj,
            )

            return True

        except Exception as e:
            print(
                f"[IMAP][BAD_SIG] Signature-only verification failed: "
                f"{type(e).__name__}: {e}"
            )
            return False

    def _is_stale_packet(self, packet_ts: Optional[float], now: Optional[float] = None) -> bool:
        if packet_ts is None:
            # No timestamp means it cannot be trusted on a shared mailbox.
            return True
        now = now or time.time()
        return (now - float(packet_ts)) > self.max_packet_age_sec

    @staticmethod
    def _fetch_response_has_flag(parts: Any, flag: str) -> bool:
        """Return True when an IMAP FETCH metadata response includes a flag."""
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

    def _get_transport_keys(self):
        try:
            uid = self._channel_uid

            signing = self.deployment["certs"][uid]["signing"]

            remote_pubkey = signing.get("pubkey") or signing.get("remote_pubkey")
            local_privkey = signing.get("remote_privkey") or signing.get("privkey")

            if not remote_pubkey or not local_privkey:
                raise RuntimeError(f"[IMAP][KEYS] Missing signing keys for uid={uid}")

            return remote_pubkey, local_privkey

        except Exception as e:
            print(f"[IMAP][KEYS][FAIL] {e}")
            return None, None

    def _decode_outer_packet(self, body: str) -> Optional[dict]:
        body = (body or "").strip()
        if not body:
            return None

        # Email bodies may have mild whitespace or forwarded text; first try the
        # clean body, then try to extract a base64-looking block.
        candidates = [body]
        candidates.extend(re.findall(r"[A-Za-z0-9+/=]{80,}", body))

        for candidate in candidates:
            try:
                decoded = base64.b64decode(candidate.strip(), validate=False).decode("utf-8")
                obj = json.loads(decoded)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue

        # Some dev/test messages may already be raw JSON.
        try:
            obj = json.loads(body)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    @staticmethod
    def _extract_rfc822_bytes(parts: Any) -> Optional[bytes]:
        """Return only the actual RFC822 byte payload from an imaplib response."""
        if not isinstance(parts, (list, tuple)):
            return None

        for response_part in parts:
            # RFC822 data is returned as (response-header, raw-message).  Other
            # entries may be bytes metadata, so never subscript them as tuples.
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
        """Normalize a MIME text payload without ever calling decode on an int."""
        if isinstance(payload, bytearray):
            payload = bytes(payload)
        if isinstance(payload, bytes):
            return payload.decode(charset or "utf-8", errors="ignore")
        if isinstance(payload, str):
            return payload
        return None

    def _extract_text_body(self, msg):
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disp = str(part.get("Content-Disposition", ""))
                if content_type == "text/plain" and "attachment" not in disp:
                    try:
                        body = self._decode_text_payload(
                            part.get_payload(decode=True),
                            part.get_content_charset(),
                        )
                        if body is not None:
                            return body
                    except Exception:
                        continue
        else:
            try:
                body = self._decode_text_payload(
                    msg.get_payload(decode=True),
                    msg.get_content_charset(),
                )
                if body is not None:
                    return body
            except Exception:
                pass
        return None

    # ------------------------------------------------------------------
    # BaseConnector contract
    # ------------------------------------------------------------------
    def send(self, packet, timeout=10):
        # This is an ingress connector. Outbound command traffic should go
        # through the selected outgoing.command connector, not here.
        return False

    def close(self, session_id=None, channel_name=None):
        self._close_imap()
        self._emit_status("disconnected")

    def _close_imap(self):
        imap = self._imap
        self._imap = None
        try:
            if imap:
                shutdown = getattr(imap, "shutdown", None)
                if callable(shutdown):
                    shutdown()
                else:
                    sock = getattr(imap, "sock", None)
                    if sock:
                        sock.close()
        except Exception:
            pass
