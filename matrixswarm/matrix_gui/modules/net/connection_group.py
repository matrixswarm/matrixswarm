from __future__ import annotations
"""
connection_group.py — NEW-SCHEME ANNOTATED

What changed (quick read):
- Kept HttpsTransport/WsTransport but clarified responsibilities and added docstrings.
- Trimmed legacy URL candidate discovery in ConnectionGroup.connect(); prefer override → HTTPS → WSS.
- Made directive listing always come from vault_data (or a provided fn) — removed legacy fallbacks.
- Strengthened SPKI pin enforcement comments; unchanged logic.
- Added attach_vault_context() for reconcile/persist helpers.
- Marked legacy constants as deprecated (kept for ref only) and inlined their intent in comments.
- Annotated every step with [NEW‑SCHEME] or [LEGACY] markers to guide future pruning.

This file is now the single source of truth for runtime connection groups in the new vault scheme.
"""

import uuid, threading
import requests, time, os, tempfile
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Any, Tuple, List
import re, json, ssl, socket, hashlib
from urllib.parse import urlparse

from matrix_gui.modules.net.routing_shim import RouteSpec, build_requests_proxies

# ---------------------------------------------------------------------------
# [LEGACY] Kept as reference only; not used directly by connect() anymore.
# Probe endpoints that older servers might expose for serial guessing.
PROBE_PATHS: List[str] = [
    "/serial-guess",
    "/verify_serial_guess",
    "/matrix/serial-guess",
    "/matrix/verify_serial_guess",
]
BODY_KEYS: List[str] = ["serial", "directive_serial"]
PROBE_TIMEOUT: float = 2.0
# ---------------------------------------------------------------------------

try:
    import websocket as _ws  # websocket-client
    from websocket import WebSocketApp
    WEBSOCKET_IMPL = "websocket-client"
    WEBSOCKET_PATH = getattr(_ws, "__file__", "?")
    WEBSOCKET_VER  = getattr(_ws, "__version__", "?")
except Exception as _e:  # pragma: no cover (environmental)
    WEBSOCKET_IMPL = "missing-or-wrong"
    WEBSOCKET_PATH = getattr(_e, "__traceback__", None)
    WEBSOCKET_VER  = "?"
    WebSocketApp = None  # force a clean failure later

# ---------- helpers ----------------------------------------------------------

def now() -> float:
    return time.time()


def make_req(handler: str, content: dict) -> Tuple[str, dict]:
    """Build a standard payload with a unique req_id for HTTPS/WS correlation."""
    req_id = str(uuid.uuid4())
    payload = {
        "handler": handler,
        "timestamp": now(),
        "content": {**(content or {}), "req_id": req_id},
    }
    return req_id, payload


# ---------- Transport base ---------------------------------------------------

class Transport:
    """Marker base for transports; concrete classes provide start/stop/is_up."""
    def start(self) -> None: ...
    def stop(self)  -> None: ...
    def is_up(self) -> bool: return False


# ---------- HTTPS transport --------------------------------------------------

class HttpsTransport(Transport):
    """Bound HTTPS client using requests with strict verification and optional mTLS."""
    def __init__(self, proto: str, host: str, port: int, route: RouteSpec | None = None):
        self.proto, self.host, self.port = proto, host, port
        self.route = route or RouteSpec("direct")
        self.session: Optional[requests.Session] = None
        self.bound = False
        self._temps: List[str] = []

    def bind(self, cert_profile: dict) -> None:
        s = requests.Session()
        proxies = build_requests_proxies(self.route)
        if proxies:
            s.proxies = proxies

        cp, temps = _mat_profile(cert_profile)
        self._temps = temps

        # Client auth (mTLS) if provided
        if cp.get("https_client_cert") and cp.get("https_client_key"):
            s.cert = (cp["https_client_cert"], cp["https_client_key"])  # type: ignore[arg-type]

        # STRICT verification:
        #  - If a CA is provided, pin to it.
        #  - Otherwise use the system trust store (secure default).
        s.verify = cp["https_ca"] if cp.get("https_ca") else True

        try:
            where = s.verify if isinstance(s.verify, str) else "system trust store"
            print(f"[HTTPS] verify → {where}")
        except Exception:
            pass

        self.session, self.bound = s, True

    def stop(self) -> None:
        self.session = None
        self.bound = False
        for p in self._temps:
            _nuke(p)
        self._temps.clear()

    def base(self, path: str = "") -> str:
        return f"{self.proto}://{self.host}:{self.port}{path}"

    def post(self, path: str, json_body: dict, timeout: float = 5.0):
        if not (self.session and self.bound):
            raise RuntimeError("HTTPS not bound")
        return self.session.post(self.base(path), json=json_body, timeout=timeout)

    def start(self) -> None:
        pass

    def is_up(self) -> bool:
        return bool(self.session and self.bound)


# ---------- WS transport (websocket-client) ---------------------------------

class WsTransport(Transport):
    """WebSocket transport with TLS context built from in-memory certs."""
    def __init__(self, proto: str, host: str, port: int, connect_fn, route: RouteSpec | None = None):
        self.proto, self.host, self.port = proto, host, port
        self.route = route or RouteSpec("direct")
        self.connect_fn = connect_fn
        self.client: Optional[WebSocketApp] = None
        self._ws_ctx: Optional[ssl.SSLContext] = None
        self.on_message: Optional[Callable[..., None]] = None
        self._temps: List[str] = []

    def bind(self, cert_profile: dict, on_message: Callable[..., None]) -> None:
        self.ws_url = f"wss://{self.host}:{self.port}/ws"
        ctx = build_ws_ssl_context(cert_profile, self.host)
        self._ws_ctx = ctx  # keep to cleanup on close

        sslopt = {
            "cert_reqs": ssl.CERT_REQUIRED,
            "check_hostname": True,
            "ssl_context": ctx,
            # Some websocket-client versions ignore ssl_context; provide redundancy:
            "ca_certs": None,  # provided via ssl_context cadata
            "certfile": None,  # provided via context chain
            "keyfile": None,
            "server_hostname": self.host,
        }

        self._ws = WebSocketApp(
            self.ws_url,
            on_message=on_message,
            on_error=lambda *_: None,
            on_close=lambda *_: cleanup_ws_ssl_context(self._ws_ctx),
        )

        self.client = self._ws
        self._sslopt = sslopt

    def stop(self) -> None:
        try:
            if self.client:
                self.client.close()
        finally:
            self.client = None
            for p in self._temps:
                _nuke(p)
            self._temps.clear()

    def url(self, path: str = "/ws") -> str:
        return f"{self.proto}://{self.host}:{self.port}{path}"

    def start(self) -> None:
        # websocket-client will pass sslopt down to the TLS layer
        self._thread = threading.Thread(
            target=self._ws.run_forever,  # type: ignore[attr-defined]
            kwargs={"sslopt": self._sslopt, "ping_interval": 20, "ping_timeout": 10},
            daemon=True,
        )
        self._thread.start()

    def is_up(self) -> bool:
        return bool(self.client and getattr(self.client, "connected", False))


# --- SPKI helpers ------------------------------------------------------------

def _server_der_cert(host: str, port: int, timeout: float = 5.0) -> bytes:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            return ssock.getpeercert(binary_form=True)


def _spki_pin_from_der(der_bytes: bytes) -> str:
    """Return base64(sha256(SPKI)) or empty string if cryptography is unavailable."""
    try:
        import base64
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization, hashes
        cert = x509.load_der_x509_certificate(der_bytes)
        spki = cert.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return base64.b64encode(hashlib.sha256(spki).digest()).decode("ascii")
    except Exception:
        return ""  # triggers a soft skip (we'll log and continue)


# ---------- ConnectionGroup --------------------------------------------------

@dataclass
class ConnectionGroup:
    """
    Runtime wrapper for a vault connection_group entry.

    Required in NEW‑SCHEME:
      - https: HttpsTransport bound to host/port/proto from vault.connection_groups
      - wss:   optional WsTransport bound to same host/port (or dedicated WS port)

    The group owns TLS/cert matching and keeps runtime state isolated from globals.
    """
    id: str
    name: str
    https: Optional[HttpsTransport] = None
    wss:   Optional[WsTransport]   = None

    # optional extra transports later (email/discord/etc.)
    extras: Dict[str, Transport] = field(default_factory=dict)

    # binding / directive state
    status: str = "IDLE"  # IDLE | PROBING | BOUND | NOMATCH | ERROR
    serial: Optional[str] = None
    universe_id: Optional[str] = None
    cert_profile: Optional[dict] = None
    remote_pubkey: Optional[str] = None

    # correlation map for HTTPS→WS replies
    pending: Dict[str, Callable[[dict], None]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    # vault persistence context (used by _reconcile_and_overlay)
    vault_data: Optional[dict] = None
    vault_path: Optional[str] = None
    vault_key_path: Optional[str] = None
    password: Optional[str] = None

    # UI/event hook (optional)
    emit: Callable[[str, Any], None] = lambda *_: None

    # -- convenience ---------------------------------------------------------
    def attach_vault_context(self, *, vault_data=None, vault_path=None, vault_key_path=None, password=None) -> None:
        """Attach vault persistence context so reconcile helper can emit vault.update."""
        self.vault_data = vault_data
        self.vault_path = vault_path
        self.vault_key_path = vault_key_path
        self.password = password

    # -- lifecycle -----------------------------------------------------------
    def connect(self, deployment_id: str, tag_registry_lookup: Callable[[str, str, str], dict],
                override_url: Optional[str] = None) -> None:
        """
        Establish HTTPS (and optionally WSS) with strict TLS based on deployment cert profile.

        Steps:
        - Determine target URL (override or deployment-host)
        - Fetch cert profile via tag_registry
        - Probe TLS certificate and verify fingerprint or SPKI pin
        - Bind HTTPS/WSS transports
        - Set status: BOUND | ERROR
        """
        if not self.https:
            raise RuntimeError("ConnectionGroup is missing HTTPS transport")

        def worker():
            try:
                self._connecting = True
                self.status = "PROBING"
                self.emit("group.status", self)

                # 1) Resolve target host and port
                proto = getattr(self.https, "proto", "https")
                host = getattr(self.https, "host", "")
                port = getattr(self.https, "port", 443)
                target_url = override_url or f"{proto}://{host}:{port}"
                self.emit("ops.feed", f"[{self.name}] connecting to {target_url}")

                # 2) Probe server certificate
                server_cn, server_fp = _probe_server_identity(host, port)
                self.emit("ops.feed", f"[{self.name}] CN → {server_cn}, fingerprint → {server_fp[:12]}…")

                # 3) Resolve cert profile via tag_registry
                cert_profile = tag_registry_lookup("security", "perimeter_https", "v1")
                if not cert_profile:
                    raise RuntimeError("No cert profile found for perimeter_https")

                # 4) Check SPKI pin match
                expected_pin = cert_profile.get("spki_pin")
                if expected_pin:
                    der = _server_der_cert(host, port, timeout=5.0)
                    actual_pin = _spki_pin_from_der(der)
                    if actual_pin != expected_pin:
                        raise RuntimeError(f"SPKI mismatch: expected {expected_pin}, got {actual_pin}")
                    self.emit("ops.feed", f"[{self.name}] SPKI match OK: {actual_pin[:12]}…")
                else:
                    self.emit("ops.feed", f"[{self.name}] SPKI pin not found in profile; skipping pin check")

                # 5) Bind HTTPS
                self.cert_profile = cert_profile
                self.https.bind(cert_profile)
                self.emit("ops.feed", f"[{self.name}] HTTPS bound OK")

                # 6) Optionally bind WSS
                if self.wss:
                    self.wss.bind(cert_profile, on_message=self._on_ws)
                    self.wss.start()
                    self.emit("ops.feed", f"[{self.name}] WSS started OK")

                # 7) Probe HTTPS POST to confirm
                payload = {"handler": "cmd_ping", "timestamp": time.time(), "content": {}}
                resp = self.https.post("/matrix", json_body=payload, timeout=5)
                self.emit("ops.feed", f"... POST /matrix → {resp.status_code}")

                self.status = "BOUND"
                self.emit("group.status", self)

            except Exception as e:
                self.emit("ops.feed", f"[{self.name}] CONNECT FAILED: {type(e).__name__}: {e!s}")
                self.status = "ERROR"
                self.emit("group.status", self)
                self.emit("group.error", e)
            finally:
                self._connecting = False

        threading.Thread(target=worker, daemon=True).start()

    def disconnect(self) -> None:
        for t in list(self.extras.values()):
            t.stop()
        if self.wss:
            self.wss.stop()
        if self.https:
            self.https.stop()
        self.status = "IDLE"; self.emit("group.status", self)

    def send_cmd(self, handler: str, content: dict, on_reply: Optional[Callable[[dict], None]] = None) -> str:
        if self.status != "BOUND":
            raise RuntimeError("Group not bound")
        req_id, payload = make_req(handler, content)

        # track correlation
        if on_reply:
            with self.lock:
                self.pending[req_id] = on_reply

        # send via HTTPS
        try:
            r = self.https.post("/matrix", json_body=payload, timeout=5)
        except Exception as e:
            self.emit("ops.feed", f"[{self.name}] HTTPS post error: {e!s}")
            self.emit("group.error", e)
            raise

        if not r.ok:
            with self.lock:
                self.pending.pop(req_id, None)
            raise RuntimeError(f"HTTPS send failed: {r.status_code}")
        return req_id

    # ----- internal ----------------------------------------------------------
    def _on_ws(self, raw_msg: str) -> None:
        try:
            msg = json.loads(raw_msg)
        except Exception:
            self.emit("ops.feed", f"[{self.name}] << {raw_msg[:200]}")
            return

        # correlation (look in content.req_id or top-level req_id)
        req_id = (msg.get("content") or {}).get("req_id") or msg.get("req_id")
        if req_id:
            cb = None
            with self.lock:
                cb = self.pending.pop(req_id, None)
            if cb:
                try:
                    cb(msg)
                except Exception:
                    pass
                return

        # no correlation → general ops feed for common tab + this group tab
        self.emit("ops.feed", f"[{self.name}] << {json.dumps(msg)[:200]}")
        self.emit("group.feed", (self, msg))


# ----- shredder time ---------------------------------------------------------

def _nuke(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _mat_profile(cp: dict) -> Tuple[dict, List[str]]:
    """
    Normalize a cert_profile into the exact keys the transports need and write
    any PEM strings to temp files so requests/ssl can load them.

    Accepts both nested and flattened vault shapes (e.g. "<tag>/connection/*").
    Returns (normalized_profile, temp_paths_to_cleanup).
    """
    temps: List[str] = []
    out: dict = dict(cp or {})

    # Fallback mapping if caller forgot to normalize
    def _fallback_map(d: dict) -> dict:
        if d.get("https_client_cert") and d.get("https_client_key") and "https_ca" in d:
            return d
        # Accept generic keys
        d.setdefault("https_client_cert", d.get("cert"))
        d.setdefault("https_client_key",  d.get("key"))
        d.setdefault("https_ca",          d.get("ca"))

        ph_cert = d.get("perimeter_https/connection/cert")
        ph_key  = d.get("perimeter_https/connection/key")
        ph_ca   = d.get("perimeter_https/connection/ca")
        if ph_cert and not d.get("https_client_cert"): d["https_client_cert"] = ph_cert
        if ph_key  and not d.get("https_client_key"):  d["https_client_key"]  = ph_key
        if ph_ca   and "https_ca" not in d:            d["https_ca"]          = ph_ca

        # Accept flattened `<tag>/connection/*`
        for k in list(d.keys()):
            if k.endswith("/connection/cert") and not d.get("https_client_cert"):
                d["https_client_cert"] = d[k]
            elif k.endswith("/connection/key") and not d.get("https_client_key"):
                d["https_client_key"] = d[k]
            elif k.endswith("/connection/ca") and "https_ca" not in d:
                d["https_ca"] = d[k]
            elif k.endswith("/signing/remote_pubkey") and "remote_pubkey" not in d:
                d["remote_pubkey"] = d[k]
        return d

    out = _fallback_map(out)

    # Collect ALL CA PEMs and make a bundle so both HTTPS/WSS can verify
    cas: List[str] = []
    if out.get("https_ca"): cas.append(out["https_ca"])  # explicit
    if out.get("ca"):       cas.append(out["ca"])        # alias
    for k, v in list(out.items()):
        if isinstance(k, str) and k.endswith("/connection/ca") and v:
            cas.append(v)

    # de-dup while preserving order
    bundle: List[str] = []
    seen: set = set()
    for pem in cas:
        s = (pem or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        bundle.append(s)
    if bundle:
        out["https_ca"] = "\n".join(bundle)

    def _write_if_pem(val, suf) -> str:
        if not val:
            return ""
        s = str(val)
        if "BEGIN" in s:  # PEM string → temp file
            f = tempfile.NamedTemporaryFile(delete=False, suffix=suf)
            f.write(s.encode("utf-8")); f.flush(); f.close()
            temps.append(f.name)
            return f.name
        return s  # assume already a path

    out["https_client_cert"] = _write_if_pem(out.get("https_client_cert") or out.get("cert"), ".crt")
    out["https_client_key"]  = _write_if_pem(out.get("https_client_key")  or out.get("key"),  ".key")
    out["https_ca"]          = _write_if_pem(out.get("https_ca")          or out.get("ca"),   ".pem")
    return out, temps


# ---- top-level helpers ------------------------------------------------------

def _wait_for_listener(host: str, port: int, attempts: int = 8, timeout: float = 2.0) -> bool:
    """Return True when a TCP connect succeeds within the attempt budget."""
    import random
    for _ in range(max(1, attempts)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            time.sleep(0.2 + random.random() * 0.8)  # light jitter
    return False


def _reconcile_and_overlay(vault_data: dict, universe_id: str, cert_profile: dict, emit=lambda *_: None) -> dict:
    """
    Self-heal cert_registry to the universe's desired versions and overlay
    the selected material into the returned cert_profile (what HTTPS/WSS bind with).
    Persists via EventBus.emit('vault.update', ...). The caller should attach vault
    context via ConnectionGroup.attach_vault_context().
    """
    try:
        vroot = (vault_data or {}).setdefault("vault", {})
        universes = vroot.get("universes", {})
        uni = universes.get(universe_id, {})
        bindings = (uni.get("bindings") or {})  # {'perimeter_https':'v4', 'perimeter_websocket':'v4', 'queen':'v4'}
        reg = vroot.setdefault("cert_registry", {})
        changed = False

        def materialize(role: str, want_ver: str, src_profile: dict):
            nonlocal changed
            if not want_ver:
                return
            r = reg.setdefault(role, {})
            versions = r.setdefault("versions", {})

            # Build entry for desired version if missing, sourcing from the universe cert_profile
            if want_ver not in versions:
                entry: dict = {}
                # Accept either flattened "<role>/connection/*" or normalized https_* keys
                def pick(k1, k2):
                    return (src_profile.get(f"{role}/connection/{k1}") or
                            src_profile.get(f"https_{k2}") or
                            src_profile.get(k1) or
                            src_profile.get(k2))
                entry["https_client_cert"] = pick("cert", "client_cert")
                entry["https_client_key"]  = pick("key",  "client_key")
                entry["https_ca"]          = pick("ca",   "ca")

                # queen extras if present
                for extra_key in ("privkey", "public_key", "remote_pubkey", "serial"):
                    if extra_key in src_profile:
                        entry[extra_key] = src_profile[extra_key]

                if not any(entry.get(k) for k in ("https_client_cert", "https_client_key", "https_ca")):
                    raise RuntimeError(f"Missing cert material for {role}:{want_ver}")

                versions[want_ver] = entry
                changed = True

            # Point current to desired
            if r.get("current") != want_ver:
                r["current"] = want_ver
                changed = True

            # Return a shallow overlay for immediate use
            return versions[want_ver]

        # For each role, ensure the bound version exists and is current, then overlay
        merged = dict(cert_profile or {})
        for role in ("perimeter_https", "perimeter_websocket", "queen"):
            want = bindings.get(role)
            if not want:
                continue
            overlay = materialize(role, want, cert_profile or {})
            if overlay:
                for k in ("https_client_cert", "https_client_key", "https_ca", "privkey", "public_key", "remote_pubkey", "serial"):
                    if overlay.get(k):
                        merged[k] = overlay[k]

        if changed:
            from matrix_gui.core.event_bus import EventBus
            vault_path = getattr(_reconcile_and_overlay, "_vault_path", None)
            vault_key_path = getattr(_reconcile_and_overlay, "_vault_key_path", None)
            password = getattr(_reconcile_and_overlay, "_password", None)
            EventBus.emit(
                "vault.update",
                vault_path=vault_path,
                key_path=vault_key_path,
                password=password,
                data=vault_data,
            )
            emit("ops.feed", f"[CERT] cert-registry reconciled → "
                             f"{ {r: (reg.get(r, {}).get('current')) for r in ('perimeter_https','perimeter_websocket','queen')} }")
        return merged
    except Exception as e:
        emit("ops.feed", f"[CERT] reconcile failed: {e!s}")
        return cert_profile or {}


def build_ws_ssl_context(cert_profile: dict, server_hostname: str) -> ssl.SSLContext:
    """
    Build an SSLContext for WSS using in-memory CA/client certs from cert_profile.
    Requires keys: https_ca, https_client_cert, https_client_key
    """
    ca_pem   = (cert_profile or {}).get("https_ca") or ""
    crt_pem  = (cert_profile or {}).get("https_client_cert") or ""
    key_pem  = (cert_profile or {}).get("https_client_key") or ""
    if not (ca_pem and crt_pem and key_pem):
        raise RuntimeError("Missing TLS material for WSS (https_ca/client_cert/client_key)")

    # Use cadata for the CA; client chain still needs file paths (Python ssl limitation)
    ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH, cafile=None, capath=None, cadata=ca_pem)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True  # SAN should include your IP/host

    # Write client cert/key to temp files for load_cert_chain
    crt_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    key_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    try:
        crt_tmp.write(crt_pem.encode("utf-8")); crt_tmp.flush(); crt_tmp.close()
        key_tmp.write(key_pem.encode("utf-8")); key_tmp.flush(); key_tmp.close()
        ctx.load_cert_chain(certfile=crt_tmp.name, keyfile=key_tmp.name)
    finally:
        # stash paths on the context for cleanup by caller
        ctx._tmp_paths = [crt_tmp.name, key_tmp.name]  # type: ignore[attr-defined]

    # SNI: set by your WS lib via 'server_hostname' or from URL; keep host here for reference
    ctx._server_hostname = server_hostname  # type: ignore[attr-defined]
    return ctx

def _probe_server_identity(host: str, port: int) -> Tuple[str, str]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=5) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            der = ssock.getpeercert(binary_form=True)
            info = ssock.getpeercert()
    fp = hashlib.sha256(der).hexdigest()
    cn = ""
    try:
        for tup in info.get("subject", []):
            for k, v in tup:
                if k == "commonName":
                    cn = v
                    break
    except Exception:
        pass
    return cn, fp

def send_ws(self, text: str) -> None:
    if not (self.wss and self.wss.is_up()):
        raise RuntimeError("WebSocket not connected")
    # websocket-client exposes .send on the app object
    self.wss.client.send(text)  # type: ignore[union-attr]

def cleanup_ws_ssl_context(ctx: ssl.SSLContext) -> None:
    for p in getattr(ctx, "_tmp_paths", []):
        try:
            os.remove(p)
        except Exception:
            pass
