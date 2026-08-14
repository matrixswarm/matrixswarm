# Authored by Commander & ChatGPT 5.5 — MatrixSwarm BootAgent Edition
# MATRIX_EMAIL_EGRESS — Secure SMTP Egress Agent (Refactored for Lane Separation)
import os
import sys

sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

import time
import threading
import json
import base64
import imaplib
import socket
import smtplib
import email

from Crypto.PublicKey import RSA
from email.message import EmailMessage
from core.python_core.boot_agent import BootAgent
from core.python_core.utils.swarm_sleep import interruptible_sleep
from core.python_core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from core.python_core.utils.crypto_utils import encrypt_with_ephemeral_aes, sign_data, pem_fix
from core.python_core.utils.mail_tls import create_mail_tls_context


class Agent(BootAgent):
    """
    MATRIX_EMAIL_EGRESS — SMTP-based secure egress agent with WebSocket-inspired security.

    Configuration Structure:
      • config/payload_lane     → Used for fetching mail (IMAP) and sending to Phoenix.
      • config/heartbeat_lane   → Used for sending heartbeats back to Phoenix.

    Queue Behavior:
      • FIFO/snake queue — oldest messages deleted first when limit exceeded.
      • Queue depth limited to ~10 emails to avoid flooding.
      • Encryption enforced (ephemeral AES + RSA signature).
    """

    def __init__(self):
        super().__init__()

        try:
            self.AGENT_VERSION = "2.1.0"  # Updated version for lane separation

            cfg = self.tree_node.get("config", {})

            # --- Initialize Working Directories (Crucial for Filesystem Ops) ---
            self.queue_dir = os.path.join(self.path_resolution["comm_path_resolved"], "queue")
            self.broadcast_dir = os.path.join(self.path_resolution["comm_path_resolved"], "broadcast")
            os.makedirs(self.queue_dir, exist_ok=True)
            os.makedirs(self.broadcast_dir, exist_ok=True)

            # Unique-but-stable flag id for the email path (like WebSocket session flags)
            uid = self.command_line_args.get('universal_id')
            self._broadcast_sid = f"email.{uid}" if uid else f"email.{self.agent_name}"

            # --- CRITICAL: Bifurcated Config Loading ---
            # Payload Lane (Swarm -> Phoenix)
            # Access the specific agent configuration block
            email_cfg = cfg.get("email_egress", {}) or {}

            # 1. Payload Lane (Swarm -> Phoenix)
            payload_lane = email_cfg.get("payload_lane", {}) or {}

            # 2. Heartbeat Lane (Phoenix -> Swarm/Flag Update) - NOW ACCESSIBLE!
            self.heartbeat_lane = email_cfg.get("heartbeat_lane", {}) or {}

            # --- Extract Identity from Payload Lane (The "Sender") ---
            smtp_cfg = payload_lane.get("smtp", {}) or {}
            monitor_cfg = payload_lane.get("imap", {}) or payload_lane.get("monitor", {}) or payload_lane.get(
                "mailbox_monitor", {})


            # Heartbeat Lane (Phoenix -> Swarm): receive heartbeat emails.
            # SMTP may still exist for payload egress, but heartbeat liveness is discovered
            # by polling IMAP and extracting the Phoenix session_id from the heartbeat.
            hb_imap_cfg = (
                self.heartbeat_lane.get("imap", {})
                or self.heartbeat_lane.get("monitor", {})
                or self.heartbeat_lane.get("mailbox_monitor", {})
                or {}
            )

            # --- Perimeter (Lockdown) ---
            self.lockdown_state = cfg.get("lockdown_state", False)
            self.lockdown_time = int(cfg.get("lockdown_time", 0))
            self.lockdown_expires = 0

            # --- Payload Lane SMTP (Sending to Phoenix) ---
            self.smtp_server = smtp_cfg.get("server") or smtp_cfg.get("host")
            self.smtp_port = int(smtp_cfg.get("port") or smtp_cfg.get("port", 587))
            self.from_address = smtp_cfg.get("username") or smtp_cfg.get("username")
            self.password = smtp_cfg.get("password") or smtp_cfg.get("password")
            self.to_address = smtp_cfg.get("to") or payload_lane.get("smtp_to")  # Fallback to top level if needed
            self.encryption = (smtp_cfg.get("encryption") or "TLS").upper().strip()
            self.subject_prefix = payload_lane.get("subject_prefix", "Matrix Packet")

            # --- Payload Lane IMAP (Fetching from Swarm) ---
            self.imap_host = monitor_cfg.get("host") or monitor_cfg.get("incoming_server")
            self.imap_port = int(monitor_cfg.get("port") or monitor_cfg.get("incoming_port") or 993)
            self.imap_user = monitor_cfg.get("username") or monitor_cfg.get("incoming_username")
            self.imap_pass = monitor_cfg.get("password") or monitor_cfg.get("incoming_password")
            self.imap_folder = monitor_cfg.get("folder", "INBOX")
            self.monitor_enabled = bool(self.imap_host and self.imap_user)

            # --- Heartbeat Lane IMAP (Phoenix -> Swarm liveness pings) ---
            # Fallback to payload monitor if heartbeat_lane.imap is omitted.
            self.hb_imap_host = hb_imap_cfg.get("host") or hb_imap_cfg.get("incoming_server") or self.imap_host
            self.hb_imap_port = int(hb_imap_cfg.get("port") or hb_imap_cfg.get("incoming_port") or self.imap_port or 993)
            self.hb_imap_user = hb_imap_cfg.get("username") or hb_imap_cfg.get("incoming_username") or self.imap_user
            self.hb_imap_pass = hb_imap_cfg.get("password") or hb_imap_cfg.get("incoming_password") or self.imap_pass
            self.hb_imap_folder = hb_imap_cfg.get("folder", self.imap_folder or "INBOX")
            self.hb_subject_prefix = self.heartbeat_lane.get("subject_prefix", "[MatrixSwarm-Heartbeat]")
            self.heartbeat_monitor_enabled = bool(self.hb_imap_host and self.hb_imap_user and self.hb_imap_pass)

            # Session-aware heartbeat tracking. Phoenix can open multiple sessions
            # on the same deployment, so never collapse liveness into one global flag.
            self.heartbeat_timeout_sec = int(
                self.heartbeat_lane.get("timeout_sec")
                or self.heartbeat_lane.get("stale_after_sec")
                or self.heartbeat_lane.get("ttl_sec")
                or 75
            )
            self.heartbeat_flag_refresh_sec = int(self.heartbeat_lane.get("flag_refresh_sec", 15))
            self._heartbeat_sessions = {}  # session_id -> {"last_seen": float, "last_flag_update": float}
            self._hb_lock = threading.Lock()

            # --- Flow Control & Queue Limits ---
            self.poll_interval = int(payload_lane.get("poll_interval", 20))
            self._msg_retrieval_limit = int(payload_lane.get("msg_retrieval_limit", 10))
            self.mailbox_flood_limit = int(cfg.get("mailbox_flood_limit", 25))
            self.mailbox_hard_limit = int(cfg.get("mailbox_hard_limit", max(self.mailbox_flood_limit * 3, 100)))
            self.max_send_per_cycle = int(payload_lane.get("max_send_per_cycle", 3))
            self.packet_ttl = int(cfg.get("packet_ttl", 300))

            # --- Security Material (Signing) ---
            signing_cfg = cfg.get("security", {}).get("signing", {}) or {}
            self.remote_pubkey = signing_cfg.get("remote_pubkey")  # Recipient pubkey (Phoenix)
            self.local_privkey = signing_cfg.get("privkey")  # Our signing key

            self._peer_pub_key_pem = pem_fix(self.remote_pubkey) if self.remote_pubkey else None
            self._signing_key_obj = None
            if self.local_privkey:
                self._signing_key_obj = RSA.import_key(pem_fix(self.local_privkey).encode())

            # --- Local State (Snake Queue Tracking) ---
            self._cfg_lock = threading.Lock()
            self._last_flag_cleanup = 0
            self.mailbox_depth = 0
            self.mailbox_total = 0
            self.mailbox_flooded = False
            self.last_sent_ts = 0
            self.last_sent_subject = None
            self.last_send_error = None

            # Keep the connector id stable, but session liveness is tracked per Phoenix session_id.
            uid = self.command_line_args.get('universal_id') if hasattr(self, 'command_line_args') else None
            self._connector_sid = f"email.{uid}" if uid else f"email.{self.agent_name}"

            if not self.remote_pubkey or not self.local_privkey:
                self.log("[MATRIX_EMAIL_EGRESS][INIT][ERROR] Missing signing keys for secure egress.")

            self._emit_beacon = self.check_for_thread_poke("worker", timeout=300, emit_to_file_interval=10)

        except Exception as e:
            self.log("[MATRIX_EMAIL_EGRESS][INIT][FATAL]", error=e)

    # ------------------------------------------------------------
    # Broadcast flag helpers (email path analog to WebSocket session flags)
    # ------------------------------------------------------------
    def _safe_flag_session_id(self, session_id):
        """
        Keep filesystem flag names boring and deterministic.
        Phoenix session ids are UUID-ish, but this prevents path tricks if the
        heartbeat ever comes from a malformed source.
        """
        sid = str(session_id or "").strip()
        if not sid:
            return ""
        return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in sid)

    def update_broadcast_flag(self, session_id=None, remove=False):
        """
        Email heartbeat flags are per Phoenix session, not per deployment.
        This matters because Phoenix can open multiple sessions against the same
        deployment and each one needs its own channel-open marker.
        """
        sid = self._safe_flag_session_id(session_id)
        if not sid:
            self.log("[EMAIL][FLAG][SKIP] Missing session_id; refusing to write global heartbeat flag.")
            return

        flag = os.path.join(self.broadcast_dir, f"connected.flag.email.{sid}")
        if remove:
            try:
                if os.path.exists(flag):
                    os.remove(flag)
            except Exception as e:
                self.log("[EMAIL][FLAG][REMOVE][ERROR]", error=e)
            return

        try:
            with open(flag, "w", encoding="utf-8"):
                pass
            os.utime(flag, None)
        except Exception as e:
            self.log("[EMAIL][FLAG][WRITE][ERROR]", error=e)

    def _cleanup_old_broadcast_flags(self):
        """
        Delete stale email heartbeat flags. A session is considered alive only
        if a heartbeat for that exact session_id is still arriving.
        """
        try:
            now = time.time()
            with self._hb_lock:
                active = set(self._heartbeat_sessions.keys())

            for fname in os.listdir(self.broadcast_dir):
                if not fname.startswith("connected.flag.email."):
                    continue

                fpath = os.path.join(self.broadcast_dir, fname)
                sid = fname.replace("connected.flag.email.", "", 1)

                stale_by_state = sid not in active
                stale_by_mtime = now - os.path.getmtime(fpath) > self.heartbeat_timeout_sec

                if stale_by_state or stale_by_mtime:
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass
        except Exception as e:
            self.log("[EMAIL][FLAG][CLEANUP][ERROR]", error=e)

    def _connect_heartbeat_imap(self):
        if not self.heartbeat_monitor_enabled:
            return None
        try:
            socket.setdefaulttimeout(20)
            M = imaplib.IMAP4_SSL(
                self.hb_imap_host,
                self.hb_imap_port,
                ssl_context=create_mail_tls_context(),
            )
            M.login(self.hb_imap_user, self.hb_imap_pass)
            return M
        except Exception as e:
            self.log("[EMAIL][HEARTBEAT][IMAP][ERROR] Failed heartbeat IMAP connection", error=e)
            return None

    def _extract_text_body(self, msg):
        try:
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                        return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
                return ""
            return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="ignore")
        except Exception as e:
            self.log("[EMAIL][BODY][ERROR]", error=e)
            return ""

    def _walk_for_session_id(self, obj):
        if isinstance(obj, dict):
            sid = obj.get("session_id")
            if sid:
                return sid

            # Common envelope shapes, including matrix_packet wrappers.
            for key in ("heartbeat", "matrix_packet", "content", "payload", "data", "inner"):
                found = self._walk_for_session_id(obj.get(key))
                if found:
                    return found

            for value in obj.values():
                found = self._walk_for_session_id(value)
                if found:
                    return found

        elif isinstance(obj, list):
            for value in obj:
                found = self._walk_for_session_id(value)
                if found:
                    return found

        return None

    def _extract_heartbeat_session_id(self, subject, body):
        """
        Extract session_id from the heartbeat email without using swarm cmd_*.
        Preferred heartbeat body:
            {"type":"heartbeat","session_id":"<phoenix-session-id>","ts":...}

        Fallbacks:
          • base64(json)
          • nested JSON envelopes
          • subject suffix: [MatrixSwarm-Heartbeat] <session_id>
        """
        try:
            candidates = [body.strip()]

            try:
                candidates.append(base64.b64decode(body.strip()).decode("utf-8"))
            except Exception:
                pass

            for candidate in candidates:
                if not candidate:
                    continue
                try:
                    obj = json.loads(candidate)
                except Exception:
                    continue

                sid = self._walk_for_session_id(obj)
                if sid:
                    return self._safe_flag_session_id(sid)

            # Last ditch: allow subject-carried session id.
            subj = str(subject or "").strip()
            if self.hb_subject_prefix and self.hb_subject_prefix in subj:
                sid = subj.split(self.hb_subject_prefix, 1)[-1].strip(" :-—[]()")
                if sid:
                    return self._safe_flag_session_id(sid)

        except Exception as e:
            self.log("[EMAIL][HEARTBEAT][EXTRACT][ERROR]", error=e)

        return None

    def _record_heartbeat(self, session_id):
        sid = self._safe_flag_session_id(session_id)
        if not sid:
            return False

        now = time.time()
        with self._hb_lock:
            state = self._heartbeat_sessions.setdefault(sid, {})
            state["last_seen"] = now

            # Emulate longer liveness windows by touching the filesystem flag in
            # 15-second intervals while the session remains alive.
            if now - state.get("last_flag_update", 0) >= self.heartbeat_flag_refresh_sec:
                self.update_broadcast_flag(session_id=sid, remove=False)
                state["last_flag_update"] = now

        return True

    def _refresh_live_heartbeat_flags(self):
        """
        Keep flags warm every 15 seconds as long as the most recent heartbeat is
        still inside the timeout window. Delete the flag once that window expires.
        """
        now = time.time()
        expired = []

        with self._hb_lock:
            for sid, state in list(self._heartbeat_sessions.items()):
                if now - state.get("last_seen", 0) > self.heartbeat_timeout_sec:
                    expired.append(sid)
                    continue

                if now - state.get("last_flag_update", 0) >= self.heartbeat_flag_refresh_sec:
                    self.update_broadcast_flag(session_id=sid, remove=False)
                    state["last_flag_update"] = now

            for sid in expired:
                self._heartbeat_sessions.pop(sid, None)

        for sid in expired:
            self.update_broadcast_flag(session_id=sid, remove=True)
            self.log(f"[EMAIL][HEARTBEAT][STALE] Session expired; flag removed: {sid}")

    def _poll_heartbeat_mailbox(self):
        """
        Poll heartbeat IMAP, consume heartbeat messages, and mark the matching
        Phoenix session_id alive. This is the email-wire path; it intentionally
        does not use cmd_* because those are swarm commands.
        """
        if not self.heartbeat_monitor_enabled:
            return

        M = self._connect_heartbeat_imap()
        if not M:
            return

        try:
            M.select(self.hb_imap_folder)
            typ, data = M.search(None, "UNSEEN")
            if typ != "OK" or not data or not data[0]:
                return

            for msg_id in data[0].split():
                status, parts = M.fetch(msg_id, "(RFC822)")
                if status != "OK" or not parts:
                    continue

                raw_msg = parts[0][1]
                msg = email.message_from_bytes(raw_msg)
                subject = msg.get("Subject", "")

                if self.hb_subject_prefix and self.hb_subject_prefix not in str(subject):
                    continue

                body = self._extract_text_body(msg)
                sid = self._extract_heartbeat_session_id(subject, body)

                if not sid:
                    self.log(f"[EMAIL][HEARTBEAT][DROP] No session_id found in heartbeat subject={subject!r}")
                    continue

                if self._record_heartbeat(sid):
                    M.store(msg_id, "+FLAGS", "\\Seen")
                    self.log(f"[EMAIL][HEARTBEAT][RX] session_id={sid}")

        except Exception as e:
            self.log("[EMAIL][HEARTBEAT][POLL][ERROR]", error=e)
        finally:
            try:
                M.logout()
            except Exception:
                pass

    # ------------------------------------------------------------
    # SMTP + IMAP monitor (like WebSocket mTLS + signature verification)
    # ------------------------------------------------------------
    def _connect_imap_monitor(self):
        if not self.monitor_enabled:
            return None
        try:
            socket.setdefaulttimeout(20)
            M = imaplib.IMAP4_SSL(
                self.imap_host,
                self.imap_port,
                ssl_context=create_mail_tls_context(),
            )
            M.login(self.imap_user, self.imap_pass)
            return M
        except Exception as e:
            self.log("[MATRIX_EMAIL_EGRESS][IMAP][ERROR] Failed IMAP monitor connection", error=e)
            return None

    def _get_mailbox_depth(self):
        if not self.monitor_enabled:
            return {
                "unseen": 0,
                "total": 0,
                "ok": False,
                "reason": "monitor_disabled",
            }

        M = self._connect_imap_monitor()
        if not M:
            return {
                "unseen": 0,
                "total": 0,
                "ok": False,
                "reason": "imap_connect_failed",
            }

        unseen = 0
        total = 0
        try:
            M.select(self.imap_folder)

            typ, unseen_data = M.search(None, "UNSEEN")
            if typ == "OK" and unseen_data and unseen_data[0]:
                unseen = len(unseen_data[0].split())

            typ, all_data = M.search(None, "ALL")
            if typ == "OK" and all_data and all_data[0]:
                total = len(all_data[0].split())

            return {
                "unseen": unseen,
                "total": total,
                "ok": True,
            }

        except Exception as e:
            self.log("[MATRIX_EMAIL_EGRESS][IMAP][DEPTH][ERROR]", error=e)
            return {
                "unseen": unseen,
                "total": total,
                "ok": False,
                "reason": str(e),
            }
        finally:
            try:
                M.logout()
            except Exception:
                pass

    def _smtp_send_message(self, msg: EmailMessage, timeout=20):
        context = create_mail_tls_context()

        mode = self.encryption.upper().strip()
        if mode not in ("SSL", "TLS", "STARTTLS"):
            raise ValueError(
                "SMTP encryption must be SSL, TLS, or STARTTLS"
            )

        if mode == "SSL":
            with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=timeout, context=context) as server:
                server.login(self.from_address, self.password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=timeout) as server:
                server.starttls(context=context)
                if self.from_address and self.password:
                    server.login(self.from_address, self.password)
                server.send_message(msg)

    # ------------------------------------------------------------
    # Secure packet building
    # ------------------------------------------------------------
    def _secure_envelope(self, matrix_packet: dict, session_id=None):

        if not isinstance(matrix_packet, dict):
            raise ValueError("matrix_packet must be a dict")

        ts = int(time.time())
        inner = {
            "matrix_packet": matrix_packet,
            "ts": ts,
            "session_id": session_id,
        }

        sealed = encrypt_with_ephemeral_aes(inner, self._peer_pub_key_pem)
        signed_block = {
            "content": sealed,
            "timestamp": ts,
            "expires": ts + self.packet_ttl,
        }
        signed_block["sig"] = sign_data(signed_block, self._signing_key_obj)

        return {
            "content": signed_block
        }

    def _build_email(self, job: dict) -> EmailMessage:
        matrix_packet = job.get("matrix_packet")
        if not matrix_packet:
            raise ValueError("Queue job missing matrix_packet")

        session_id = job.get("session_id")
        envelope = self._secure_envelope(matrix_packet, session_id=session_id)
        payload_b64 = base64.b64encode(json.dumps(envelope).encode()).decode()

        msg = EmailMessage()
        msg["From"] = job.get("from_addr") or self.from_address
        msg["To"] = job.get("to_addr") or self.to_address
        msg["Subject"] = job.get(
            "subject") or f"{self.subject_prefix} ({self.command_line_args.get('universal_id', 'matrix_email_egress')})"
        msg.set_content(payload_b64)
        return msg

    # ------------------------------------------------------------
    # Heartbeat Logic (Ping Remote Agent)
    # ------------------------------------------------------------
    def _send_heartbeat(self):
        """
        Deprecated on purpose.

        Heartbeats are not emitted by this agent. Phoenix sends them over the
        email wire, and this agent receives them via IMAP, extracts session_id,
        and maintains per-session broadcast flags.
        """
        self.log("[EMAIL][HEARTBEAT][DISABLED] Heartbeat sending disabled; receiver mode is authoritative.")
        return False

    # ------------------------------------------------------------
    # Worker (like WebSocket lifecycle management)
    # ------------------------------------------------------------
    def worker(self, config=None, identity: IdentityObject = None):
        try:
            self._emit_beacon()

            if isinstance(config, dict) and bool(config.get("push_live_config", 0)):
                self.log(f"[ORACLE] 🔁 Live config update detected: {config}")
                self._apply_live_config(config)

            # Check Lockdown
            if self.lockdown_state and self.lockdown_time > 0:
                now = int(time.time())
                if now >= self.lockdown_expires:
                    self.log("[LOCKDOWN] Time expired. Reopening perimeter.")
                    self.toggle_perimeter(False, 0)

            # Email-wire heartbeat intake and 15s flag emulation must run
            # independently of payload send/flood state. Otherwise a mailbox
            # flood makes live Phoenix sessions look dead.
            hb_enabled = bool(self.heartbeat_lane.get("enabled", True))
            if hb_enabled:
                self._poll_heartbeat_mailbox()
                self._refresh_live_heartbeat_flags()

            # Cleanup stale files periodically. This also clears flags for
            # sessions that no longer have heartbeat state.
            if (time.time() - self._last_flag_cleanup) > 60:
                self._last_flag_cleanup = time.time()
                self._cleanup_old_broadcast_flags()

            # Check Mailbox Depth (Avoid Flooding)
            depth = self._get_mailbox_depth()
            self.mailbox_depth = int(depth.get("unseen", 0) or 0)
            self.mailbox_total = int(depth.get("total", 0) or 0)
            self.mailbox_flooded = self.mailbox_depth >= self.mailbox_flood_limit or self.mailbox_total >= self.mailbox_hard_limit

            if self.lockdown_state:
                # Remove all email session flags while perimeter is closed.
                with self._hb_lock:
                    stale_sessions = list(self._heartbeat_sessions.keys())
                    self._heartbeat_sessions.clear()
                for sid in stale_sessions:
                    self.update_broadcast_flag(session_id=sid, remove=True)

                self.log("[MATRIX_EMAIL_EGRESS][BLOCKED] Packet Processing is Off.")
                return

            # Prune queue to maintain snake depth (like WebSocket session limits)
            self._prune_queue()

            if self.mailbox_flooded:
                self.log(
                    f"[EMAIL][FLOOD] Holding outbound mail. unseen={self.mailbox_depth} total={self.mailbox_total} "
                    f"limits=({self.mailbox_flood_limit}/{self.mailbox_hard_limit})"
                )
                return

            self._drain_queue_once()

        except Exception as e:
            self.log("[MATRIX_EMAIL_EGRESS][WORKER][ERROR]", error=e)

        finally:
            interruptible_sleep(self, self.poll_interval)

    def _prune_queue(self):
        # Placeholder for queue pruning logic if implemented
        pass

    def _drain_queue_once(self):
        # Placeholder for queue draining logic
        pass

    def cmd_send_email(self, content: dict, packet: dict, identity: IdentityObject = None):
        """
        Handles the logic for sending an email packet.
        Robust against malformed packets from RPC routes.
        """
        try:
            if self.lockdown_state:
                sender = identity.get_sender_uid() if identity and identity.has_verified_identity() else packet.get(
                    "origin", "not specified")
                self.log(f"[MATRIX-EMAIL-EGRESS][BLOCKED] Packet Processing is Off. Access attempt from {sender}.")
                return

            # --- Robust Extraction ---
            # Try to get 'matrix_packet' first. If missing, check if content IS the packet.
            matrix_packet = None

            if isinstance(content, dict):
                if "matrix_packet" in content:
                    matrix_packet = content["matrix_packet"]
                elif len(content) == 0:
                    self.log("[EMAIL][CMD_SEND][WARN] Received empty content dict.")
                else:
                    # If no 'matrix_packet' key, assume the whole content is the payload (legacy/alternative format)
                    # But only if it looks like a packet (has 'type' or 'sig')
                    if "type" in content or "sig" in content:
                        matrix_packet = content

            session_id = None
            if isinstance(content, dict):
                session_id = content.get("session_id")

            if not matrix_packet:
                # Debug log to see what we actually received
                self.log(
                    f"[EMAIL][CMD_SEND][DEBUG] Received content keys: {list(content.keys()) if isinstance(content, dict) else 'N/A'}")
                return

            # Build Email Job Object
            job = {
                "matrix_packet": matrix_packet,
                "session_id": session_id,
                "from_addr": self.from_address,
                "to_addr": self.to_address,
                "subject": f"[MatrixSwarm] Packet for {self._broadcast_sid}",
            }

            # Build and Send Email
            msg = self._build_email(job)

            self._smtp_send_message(msg)

            # Update State
            self.last_sent_ts = int(time.time())
            self.last_sent_subject = msg["Subject"]
            self.log(f"[EMAIL][SEND] ✅ Sent packet to {self.to_address}")

        except Exception as e:
            self.log("[EMAIL][CMD_SEND][ERROR]", error=e)
            self.last_send_error = str(e)

    def cmd_rpc_route(self, content, packet, identity: IdentityObject = None):
        try:
            if self.lockdown_state:
                sender = identity.get_sender_uid() if identity and identity.has_verified_identity() else packet.get(
                    "origin", "not specified")
                self.log(f"[MATRIX-EMAIL-EGRESS][BLOCKED] Packet Processing is Off. Access attempt from {sender}.")
                return

            self.cmd_send_email(content, packet, identity=identity)

        except Exception as e:
            self.log("[EMAIL][ROUTER][ERROR] Failed to route email packet", error=e)

    def cmd_status(self, content, packet, identity: IdentityObject = None):
        try:
            session_id = content.get("session_id")
            token = content.get("token")
            return_handler = content.get("return_handler")
            payload = {
                "lockdown_state": "Lockdown" if self.lockdown_state else "Open",
                "lockdown_time": self.lockdown_time,
                "lockdown_expires": str(bool(self.lockdown_expires)),
                "smtp_host": self.smtp_server,
                "smtp_user": self.from_address,
                "smtp_to": self.to_address,
                "imap_monitor": bool(self.monitor_enabled),
                "imap_host": self.imap_host,
                "imap_user": self.imap_user,
                "folder": self.imap_folder,
                "poll_interval": self.poll_interval,
                "queue_depth": self._queue_depth(),
                "mailbox_depth": self.mailbox_depth,
                "mailbox_total": self.mailbox_total,
                "mailbox_flooded": self.mailbox_flooded,
                "mailbox_flood_limit": self.mailbox_flood_limit,
                "mailbox_hard_limit": self.mailbox_hard_limit,
                "last_sent_ts": self.last_sent_ts,
                "last_sent_subject": self.last_sent_subject,
                "last_send_error": self.last_send_error,
            }

            self.crypto_reply(
                response_handler=return_handler,
                payload=payload,
                session_id=session_id,
                token=token,
                rpc_role=self.tree_node.get("config", {}).get("rpc_router_role", "hive.rpc"),
            )

        except Exception as e:
            self.log(error=e, block="main_try", level="ERROR")

    def cmd_toggle_perimeter(self, content, packet, identity: IdentityObject = None):
        try:
            lockdown_state = bool(content.get("lockdown_state", True))
            lockdown_time = int(content.get("lockdown_time", 0))
            session_id = content.get("session_id")
            token = content.get("token")
            return_handler = content.get("return_handler")

            self.toggle_perimeter(lockdown_state, lockdown_time)

            payload = {
                "lockdown_state": "Lockdown" if self.lockdown_state else "Open",
                "lockdown_time": self.lockdown_time,
                "lockdown_expires": str(bool(self.lockdown_expires)),
            }

            self.crypto_reply(
                response_handler=return_handler,
                payload=payload,
                session_id=session_id,
                token=token,
                rpc_role=self.tree_node.get("config", {}).get("rpc_router_role", "hive.rpc"),
            )

            self.log(f"[LOCKDOWN] Perimeter toggled → {payload}")

        except Exception as e:
            self.log(f"[LOCKDOWN][ERROR] cmd_toggle_perimeter failed: {e}")

    def toggle_perimeter(self, lockdown_state, lockdown_time):
        self.lockdown_time = int(lockdown_time)
        if not bool(lockdown_state):
            self.lockdown_state = False
            self.lockdown_expires = 0
            self.log("[MATRIX_EMAIL_EGRESS] Packet Processing Turned On.")
        else:
            self.lockdown_state = True
            self.lockdown_expires = int(time.time()) + self.lockdown_time if lockdown_time > 0 else 0
            expires = self.lockdown_expires if self.lockdown_expires else "Never"
            self.log(f"[MATRIX_EMAIL_EGRESS] Packet Processing Turned Off. Expires: {expires}.")

    def _apply_live_config(self, cfg: dict):
        try:
            with self._cfg_lock:
                if "poll_interval" in cfg:
                    self.poll_interval = int(cfg.get("poll_interval", self.poll_interval))
                if "mailbox_flood_limit" in cfg:
                    self.mailbox_flood_limit = int(cfg.get("mailbox_flood_limit", self.mailbox_flood_limit))
                if "mailbox_hard_limit" in cfg:
                    self.mailbox_hard_limit = int(cfg.get("mailbox_hard_limit", self.mailbox_hard_limit))
                if "max_send_per_cycle" in cfg:
                    self.max_send_per_cycle = int(cfg.get("max_send_per_cycle", self.max_send_per_cycle))
                if "packet_ttl" in cfg:
                    self.packet_ttl = int(cfg.get("packet_ttl", self.packet_ttl))
        except Exception as e:
            self.log("[ORACLE][ERROR] Failed to apply live config", error=e)

    def post_boot(self):
        self.log(
            f"[MATRIX_EMAIL_EGRESS] Version {self.AGENT_VERSION} — SMTP egress online. "
            f"Queue={self.queue_dir} Monitor={'on' if self.monitor_enabled else 'off'}"
        )


if __name__ == "__main__":
    agent = Agent()
    agent.boot()
