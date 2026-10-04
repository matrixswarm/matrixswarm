"""Independent, receive-only Matrix alert transport. No GUI bus or command API.

Only operator-saved WSS targets enter this module. The sole application packet
we send is the existing signed hello; WebSocket ping/pong supplies liveness.
Network and cryptographic work run in one bounded background event loop.
"""
from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import sys
import tempfile
import threading
import time
import uuid

from .alert_access import AlertReadError, TerminalAlertBuffer, PACKET_REJECTION_REASONS
from .bridge.deployment_view import agent_nodes

MAX_FRAME = 256 * 1024
MAX_FEEDS = 16
PACKET_WINDOW = 314


def fixed_target_connector():
    try:
        from websockets.asyncio.client import connect
    except ImportError:
        raise RuntimeError("Live alerts need the Terminal alerts extra: install .[desktop,alerts]") from None

    class FixedTargetConnect(connect):
        def process_redirect(self, exc):
            # websockets follows HTTP redirects by default. A saved target may
            # never redirect this credential-bearing connection to another host.
            return exc

    return FixedTargetConnect


class PeerIdentityError(ValueError):
    pass


class PacketRejected(ValueError):
    def __init__(self, reason):
        # Only fixed codes may reach the operator/client, never exception text
        # or fields taken from a rejected packet.
        self.reason = reason if reason in PACKET_REJECTION_REASONS else "MALFORMED_PACKET"
        super().__init__(self.reason)


@dataclass(frozen=True, repr=False)
class AlertTarget:
    deployment_id: str
    agent_id: str
    serial: str
    host: str
    port: int
    client_cert: str
    client_key: str
    ca_cert: str
    server_pin: str
    signing_public: str
    signing_private: str

    @property
    def uri(self):
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"wss://{host}:{self.port}/ws"


def target_from_deployment(deployment_id, deployment):
    """Copy only the fixed WSS receiver and its trust material, never registry data."""
    try:
        matches = [a for a in agent_nodes(deployment.get("agents", []))
                   if a.get("name") == "matrix_websocket"
                   and a.get("connection", {}).get("proto") == "wss"
                   and a.get("connection", {}).get("channel") == "payload.reception"]
        if len(matches) != 1:
            raise ValueError("ambiguous receiver")
        agent = matches[0]
        conn = agent["connection"]
        host = conn["host"]
        if not isinstance(host, str) or len(host) > 253 or host != host.strip():
            raise ValueError("invalid host")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
                raise ValueError("invalid host") from None
        port = conn["port"]
        if isinstance(port, str) and port.isascii() and port.isdigit():
            port = int(port)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("invalid port")
        uid, serial = agent["universal_id"], agent["serial"]
        if not isinstance(serial, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", serial):
            raise ValueError("invalid serial")
        certs = deployment["certs"][uid]
        tls, signing = certs["connection_cert"], certs["signing"]
        values = (tls["client_cert"]["cert"], tls["client_cert"]["key"],
                  tls["ca_root"]["cert"], tls["server_cert"]["spki_pin"],
                  signing["pubkey"], signing["remote_privkey"])
        if any(not isinstance(v, str) or not v.strip() or len(v) > 65536 for v in values):
            raise ValueError("invalid trust material")
        pin = values[3].removeprefix("sha256/")
        if len(base64.b64decode(pin, validate=True)) != 32:
            raise ValueError("invalid pin")
        return AlertTarget(deployment_id, uid, serial, host, port, *values)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError(
            "Live alerts require exactly one saved matrix_websocket payload.reception "
            "WSS receiver, fixed host/port, serial, CA, client certificate/key, "
            "server SPKI pin and signing keys. Repair this deployment in Phoenix "
            "and reopen the Vault; no target override is permitted."
        ) from None


def _canonical(value):
    return json.dumps({k: v for k, v in value.items() if k != "sig"},
                      sort_keys=True, separators=(",", ":")).encode()


class AlertDecoder:
    """Authenticate and decrypt before projecting; bounded per-feed replay cache."""
    def __init__(self, target, clock=time.time):
        from Crypto.PublicKey import RSA
        self.target = target
        self.clock = clock
        self.public = RSA.import_key(target.signing_public.replace("\\n", "\n"))
        self.private = RSA.import_key(target.signing_private.replace("\\n", "\n"))
        if not self.private.has_private():
            raise ValueError("Missing private signing key")
        self.seen = OrderedDict()

    def hello(self, session_id):
        from Crypto.Hash import SHA256
        from Crypto.Signature import pkcs1_15
        hello = {"type": "hello", "session_id": session_id,
                 "agent": self.target.agent_id, "ts": int(self.clock())}
        hello["sig"] = base64.b64encode(
            pkcs1_15.new(self.private).sign(SHA256.new(_canonical(hello)))
        ).decode()
        return json.dumps(hello)

    def decode(self, frame):
        from Crypto.Cipher import AES, PKCS1_OAEP
        from Crypto.Hash import SHA256
        from Crypto.Signature import pkcs1_15
        reason = "MALFORMED_PACKET"
        try:
            if not isinstance(frame, (str, bytes)):
                raise ValueError("frame type")
            if len(frame.encode("utf-8") if isinstance(frame, str) else frame) > MAX_FRAME:
                reason = "FRAME_TOO_LARGE"
                raise ValueError("frame limit")
            packet = json.loads(frame)
            if not isinstance(packet, dict):
                raise ValueError("packet type")
            wrapper = packet if "sig" in packet else packet.get("content")
            if not isinstance(wrapper, dict):
                raise ValueError("wrapper type")
            reason = "UNEXPECTED_SENDER"
            if wrapper.get("serial") != self.target.serial:
                raise ValueError("sender identity")
            reason = "SIGNATURE_INVALID"
            pkcs1_15.new(self.public).verify(
                SHA256.new(_canonical(wrapper)), base64.b64decode(wrapper["sig"], validate=True)
            )
            reason = "TIMESTAMP_INVALID"
            stamp, now = wrapper.get("timestamp"), self.clock()
            if type(stamp) is not int or abs(now - stamp) > PACKET_WINDOW:
                raise ValueError("packet timestamp")
            reason = "PACKET_EXPIRED"
            if "expires" in wrapper and (
                type(wrapper["expires"]) is not int or now > wrapper["expires"]
            ):
                raise ValueError("packet expiry")
            for signature, expiry in list(self.seen.items()):
                if now > expiry:
                    self.seen.pop(signature)
            digest = hashlib.sha256(wrapper["sig"].encode()).digest()
            reason = "REPLAY_REJECTED"
            if digest in self.seen:
                raise ValueError("replay")
            reason = "REPLAY_CAPACITY"
            if len(self.seen) >= 4096:
                raise ValueError("replay capacity")
            reason = "DECRYPTION_FAILED"
            sealed = wrapper["content"]
            key = PKCS1_OAEP.new(self.private).decrypt(
                base64.b64decode(sealed["encrypted_key"], validate=True))
            cipher = AES.new(key, AES.MODE_GCM, nonce=base64.b64decode(sealed["nonce"], validate=True))
            inner = json.loads(cipher.decrypt_and_verify(
                base64.b64decode(sealed["payload"], validate=True),
                base64.b64decode(sealed["tag"], validate=True)))
            if not isinstance(inner, dict):
                reason = "MALFORMED_PACKET"
                raise ValueError("inner packet")
            self.seen[digest] = stamp + PACKET_WINDOW
            reason = "HANDLER_MISMATCH"
            if packet.get("handler") and packet["handler"] != inner.get("handler"):
                raise ValueError("handler mismatch")
            if inner.get("handler") != "swarm_feed.alert":
                return None  # No generic handler dispatch, even for signed packets.
            if not isinstance(inner.get("content"), dict):
                reason = "ALERT_CONTENT_INVALID"
                raise ValueError("alert content")
            return {"content": inner["content"], "event_type": "swarm_feed.alert",
                    "timestamp": datetime.fromtimestamp(stamp, timezone.utc).isoformat()}
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
            raise PacketRejected(reason) from None


def tls_context(target):
    """Require the saved CA and client identity; additionally pin the server SPKI."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Saved IP targets need not match certificate DNS names; exact SPKI is
    # checked before application authentication. CA/expiry checks stay enabled.
    context.check_hostname = False
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cadata=target.ca_cert.replace("\\n", "\n"))
    with tempfile.TemporaryDirectory(prefix="phoenix-terminal-tls-") as temporary:
        cert, key = Path(temporary) / "client.pem", Path(temporary) / "client.key"
        for path, value in ((cert, target.client_cert), (key, target.client_key)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as stream:
                stream.write(value.replace("\\n", "\n"))
        context.load_cert_chain(str(cert), str(key))
    return context


def verify_peer(connection, expected_pin):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    try:
        tls = connection.transport.get_extra_info("ssl_object")
        der = tls.getpeercert(binary_form=True)
        cert = x509.load_der_x509_certificate(der)
        spki = cert.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        pin = base64.b64encode(hashlib.sha256(spki).digest()).decode()
        if not hmac.compare_digest(pin, expected_pin.removeprefix("sha256/")):
            raise ValueError("pin mismatch")
    except (ValueError, TypeError, AttributeError):
        raise PeerIdentityError("Saved server identity did not match") from None


class LiveAlertFeeds:
    """One background loop, at most 16 fixed feeds, no network before approval."""
    def __init__(self, targets, *, connector=None, context_factory=tls_context,
                 peer_verifier=verify_peer, retry_seconds=3):
        self.targets = dict(targets)
        if len(self.targets) > MAX_FEEDS:
            raise ValueError(f"At most {MAX_FEEDS} live alert deployments are supported")
        if connector is None:
            connector = fixed_target_connector()
        self.connector = connector
        self.context_factory = context_factory
        self.peer_verifier = peer_verifier
        self.retry_seconds = retry_seconds
        self._lock = threading.RLock()
        self._buffers = {}
        self._sources = {}
        self._bindings = {}
        self._stop = threading.Event()
        self._thread = None
        self._grants = lambda: {}
        self._loop = None
        self._main_task = None
        self._failed = False

    def start(self, grant_supplier):
        if self._thread is not None:
            raise RuntimeError("Alert runtime already started")
        self._grants = grant_supplier
        self._thread = threading.Thread(target=self._thread_main, name="TerminalAlerts", daemon=True)
        self._thread.start()

    def _thread_main(self):
        try:
            asyncio.run(self._supervise())
        except asyncio.CancelledError:
            pass  # Normal bounded shutdown, not a worker failure.
        except Exception as exc:
            # Never print transport exceptions (they may embed a URL or secrets).
            print(f"[TerminalAlerts] Worker failed ({type(exc).__name__}); reopen Terminal access.", file=sys.stderr)
            with self._lock:
                self._failed = True
                for source in self._sources.values():
                    source.update(state="error", code="WORKER_FAILED", may_have_missed=True)

    async def _supervise(self):
        self._loop = asyncio.get_running_loop()
        self._main_task = asyncio.current_task()
        tasks = {}
        try:
            while not self._stop.is_set():
                grants = self._grants()
                wanted = set(grants).intersection(self.targets)
                for deployment_id in list(tasks):
                    if (deployment_id not in wanted
                            or self._bindings[deployment_id] != grants[deployment_id]):
                        task = tasks.pop(deployment_id)
                        task.cancel()
                        with self._lock:
                            self._buffers.pop(deployment_id, None)
                            self._sources.pop(deployment_id, None)
                            self._bindings.pop(deployment_id, None)
                        await asyncio.gather(task, return_exceptions=True)
                for deployment_id in wanted.difference(tasks):
                    with self._lock:
                        self._buffers[deployment_id] = TerminalAlertBuffer()
                        self._bindings[deployment_id] = grants[deployment_id]
                        self._sources[deployment_id] = {
                            "state": "connecting", "code": "CONNECTING",
                            "stream_id": uuid.uuid4().hex, "live_only": True,
                            "may_have_missed": False, "rejected_packets": 0,
                            "received_alerts": 0, "last_rejection": "",
                        }
                    tasks[deployment_id] = asyncio.create_task(self._receive(deployment_id, grants[deployment_id]))
                await asyncio.sleep(0.1)
        finally:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            with self._lock:
                self._buffers.clear()
                self._sources.clear()
                self._bindings.clear()
            self._main_task = None

    def _state(self, deployment_id, **changes):
        with self._lock:
            if deployment_id in self._sources:
                self._sources[deployment_id].update(changes)

    async def _receive(self, deployment_id, binding):
        from websockets.exceptions import WebSocketException
        target = self.targets[deployment_id]
        try:
            decoder = AlertDecoder(target)
            context = self.context_factory(target)
        except Exception:
            self._state(deployment_id, state="error", code="TRUST_MATERIAL_INVALID")
            return
        while not self._stop.is_set() and self._grants().get(deployment_id) == binding:
            try:
                async with self.connector(
                    target.uri, ssl=context, proxy=None, compression=None,
                    open_timeout=8, close_timeout=1, ping_interval=15, ping_timeout=10,
                    max_size=MAX_FRAME, max_queue=4,
                ) as connection:
                    self.peer_verifier(connection, target.server_pin)
                    if self._grants().get(deployment_id) != binding:
                        return
                    await connection.send(decoder.hello(uuid.uuid4().hex))
                    self._state(deployment_id, state="connected", code="AWAITING_ALERTS")
                    async for frame in connection:
                        if self._grants().get(deployment_id) != binding:
                            return
                        try:
                            alert = decoder.decode(frame)
                        except PacketRejected as exc:
                            with self._lock:
                                source = self._sources.get(deployment_id)
                                if source is not None:
                                    source["rejected_packets"] += 1
                                    source.update(code="PACKET_REJECTED", may_have_missed=True,
                                                  last_rejection=exc.reason)
                            continue
                        if alert is not None:
                            with self._lock:
                                if deployment_id in self._buffers:
                                    self._buffers[deployment_id].append(deployment_id, [alert])
                                    self._sources[deployment_id]["code"] = "RECEIVING_ALERTS"
                                    self._sources[deployment_id]["received_alerts"] += 1
                self._state(deployment_id, state="reconnecting", code="SOURCE_CLOSED", may_have_missed=True)
            except (PeerIdentityError, ssl.SSLError):
                self._state(deployment_id, state="error", code="PEER_IDENTITY_FAILED", may_have_missed=True)
                return  # Never retry a different key or silently weaken TLS.
            except (OSError, TimeoutError, WebSocketException):
                self._state(deployment_id, state="reconnecting", code="CONNECTION_FAILED", may_have_missed=True)
            except Exception as exc:
                self._state(deployment_id, state="error", code="WORKER_FAILED", may_have_missed=True)
                print(f"[TerminalAlerts] Feed failed ({type(exc).__name__}); inspect adapter code.", file=sys.stderr)
                return
            await asyncio.sleep(self.retry_seconds)

    def read(self, deployment_id, after, limit):
        # Broker is the authority. This extra guard also protects private callers.
        binding = self._grants().get(deployment_id)
        if binding is None:
            raise PermissionError("No active alert grant")
        with self._lock:
            if self._failed:
                raise AlertReadError("Alert worker failed; reopen Terminal access after diagnosis")
            if deployment_id not in self._buffers or self._bindings.get(deployment_id) != binding:
                raise AlertReadError("Alert connection is starting; retry shortly")
            try:
                page = self._buffers[deployment_id].read(deployment_id, after, limit)
            except ValueError:
                raise AlertReadError("Invalid or stale alert cursor; restart with --after 0") from None
            page["source"] = dict(self._sources[deployment_id])
            return page

    def close(self):
        self._stop.set()
        loop, task = self._loop, self._main_task
        if loop is not None and task is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass  # The loop finished concurrently.
        if self._thread is not None:
            self._thread.join(timeout=2)
        with self._lock:
            self._buffers.clear()
            self._sources.clear()
            self._bindings.clear()
        self.targets.clear()

    def statuses(self):
        """Operator-window diagnostics, without endpoints or credentials."""
        with self._lock:
            if self._failed:
                return {"Alert worker": {"state": "error", "code": "WORKER_FAILED",
                                         "received_alerts": 0, "rejected_packets": 0,
                                         "last_rejection": ""}}
            return {key: {field: value[field] for field in (
                        "state", "code", "received_alerts", "rejected_packets", "last_rejection")}
                    for key, value in self._sources.items()}
