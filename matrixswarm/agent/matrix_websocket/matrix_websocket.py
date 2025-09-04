import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))
#Authored by Daniel F MacDonald and ChatGPT aka The Generals
import ssl
import time
import copy
import threading
import asyncio
import websockets
import json
import base64
from Crypto.Cipher import AES
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256
from matrixswarm.core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject
from matrixswarm.core.utils.swarm_trustkit import extract_spki_pin_from_cert
from matrixswarm.core.boot_agent import BootAgent
from matrixswarm.core.utils.crypto_utils import pem_fix
from matrixswarm.core.utils.cert_loader import load_cert_chain_from_memory
from matrixswarm.core.utils.swarm_sleep import interruptible_sleep
from matrixswarm.core.utils import crypto_utils

class Agent(BootAgent):
    def __init__(self):
        super().__init__()
        self.AGENT_VERSION = "2.0.0"


        try:

            config = self.tree_node.get("config", {})
            self.allowlist_ips = config.get("allowlist_ips", [])
            self.port = config.get("port", 8765)
            self._websocket_clients = set()
            self._sessions = {}
            self.loop = None
            self.websocket_ready = False
            self.interval = 10
            self.first_run = True

            security = self.tree_node.get("config", {}).get("security", {})  # dict now
            conn = security.get("connection", {}) or {}

            server_cert = conn.get("server_cert", {})
            client_cert = conn.get("client_cert", {})
            ca_root = conn.get("ca_root", {})

            self.cert_pem = pem_fix(server_cert.get("cert")) if server_cert.get("cert") else None
            self.key_pem = pem_fix(server_cert.get("key")) if server_cert.get("key") else None
            self.ca_pem = pem_fix(ca_root.get("cert")) if ca_root.get("cert") else None

            # Compute SPKI pin directly from memory
            try:
                self.local_spki = extract_spki_pin_from_cert(self.cert_pem.encode())
            except Exception as e:
                self.local_spki = None
                self.log("[WS][SPKI][WARN] Could not compute local SPKI pin", error=e)

            # --- Suspenders: load our signing private key (minted & embedded at deploy)
            signing_cfg = security.get("signing", {}) or {}
            signing_cfg = security.get("signing", {})
            peer_pub_pem = signing_cfg.get("remote_pubkey")
            self.peer_pub_key = RSA.import_key(peer_pub_pem.encode()) if peer_pub_pem else None
            ws_priv_pem = signing_cfg.get("privkey")
            try:
                self.ws_priv = RSA.import_key(ws_priv_pem.encode()) if ws_priv_pem else None
                if self.ws_priv:
                    self.log("[WS][SIGN] Private key loaded for outbound signing.")
                else:
                    self.log("[WS][SIGN][WARN] No signing privkey present in config.security.signing.privkey")
            except Exception as e:
                self.ws_priv = None
                self.log("[WS][SIGN][ERROR] Failed to load signing private key", error=e)

            self.log("[CERT-LOADER] Embedded certs loaded into memory.")

        except Exception as e:
            self.log("[CERT-LOADER][FATAL] Failed to load certs from config.security.connection", error=e, block="init")
            time.sleep(2)
            self.run_server_retries = False


        self._stop_event = None
        self._thread = None
        self._config = None
        self._lock = threading.Lock()
        self.emit_process_beacon = self.check_for_thread_poke(
            "websocket_process", timeout=60, emit_to_file_interval=30
        )
        self.emit_service_beacon = self.check_for_thread_poke(
            "websocket_service", timeout=60, emit_to_file_interval=30
        )

    def post_boot(self):
        self.log(f"{self.NAME} v{self.AGENT_VERSION} – perimeter guard up.")

    def worker(self, config:dict = None, identity:IdentityObject = None):
        """
        Starts or restarts the WebSocket thread if config changes or thread is dead.
        """
        try:

            self.emit_process_beacon()
            if config is None:
                config = self.tree_node.get("config", {})  # Default fallback

            with self._lock:
                if self._thread and self._thread.is_alive():
                    if config == self._config:
                        # Config unchanged, thread alive — do nothing
                        return
                    else:
                        self.log("[WS] Launching WebSocket thread... Or Config changed and restarting thread...")
                        self._stop_event.set()
                        self._thread.join(timeout=3)
                elif self._thread and not self._thread.is_alive():
                    self.log("[WS] Previous thread is dead — restarting...")

                # Start new thread
                self._config = copy.deepcopy(config)  # Defensive copy
                self._stop_event = threading.Event()
                self._thread = threading.Thread(target=self.start_socket_loop, daemon=True)
                self._thread.start()
                self.log("[WS] WebSocket thread started.")


        except Exception as e:

            self.log(error=e, block="main_try")

        interruptible_sleep(self, self.interval)


    def start_socket_loop(self):
        try:
            self.log("[WS] Booting WebSocket TLS thread...")
            time.sleep(1)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.loop = loop

            async def launch():
                self.log("[WS] Preparing SSL context...")
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_REQUIRED

                if self.cert_pem and self.key_pem:
                    load_cert_chain_from_memory(ssl_context, self.cert_pem, self.key_pem)

                # Load CA root from memory if present
                if self.ca_pem:
                    ssl_context.load_verify_locations(cadata=self.ca_pem)
                    self.log("[WS][DEBUG] Loaded CA root from memory")
                else:
                    self.log("[WS][WARN] No client CA provided — clients may not present a cert")

                try:
                    server = await websockets.serve(
                        self.websocket_handler,
                        host="0.0.0.0",
                        port=self.port,
                        ssl=ssl_context,
                        ping_interval=None,
                        ping_timeout=None,
                    )

                    self.log("[WS][BOOT] Listener bound")
                except Exception as e:
                    self.log(f"[WS][BOOT ERROR] {e}")
                    return

                self.websocket_ready = True
                self.log(f"[WS] SECURE WebSocket bound on port {self.port} (TLS enabled)")

                # Service beacon heartbeat inside the loop
                async def service_heartbeat():
                    while not self._stop_event.is_set():
                        self.emit_service_beacon()
                        await asyncio.sleep(30)

                loop.create_task(service_heartbeat())

                async def refresh_broadcast_flag():
                    while not self._stop_event.is_set():
                        # bump all active session flags
                        for sid in list(self._sessions.keys()):
                            self.update_broadcast_flag(session_id=sid)
                        await asyncio.sleep(15)

                loop.create_task(refresh_broadcast_flag())

                await server.wait_closed()

            loop.run_until_complete(launch())

            async def monitor_stop():
                while not self._stop_event.is_set():
                    await asyncio.sleep(1)
                self.log("[WS] Stop event received — shutting down WebSocket server.")
                loop.stop()

            loop.create_task(monitor_stop())
            loop.run_forever()
            loop.close()
            self.log("[WS] Event loop closed.")

        except Exception as e:
            self.log("[WS][FATAL] WebSocket startup failed", error=e, block="main_try")
            self.running = False


    def cmd_health_report(self, content, packet, identity:IdentityObject = None):
        self.log(f"[RELAY] Received health report for {content.get('target_universal_id', '?')}")

    async def websocket_handler(self, websocket):
        try:
            await self._websocket_handler_core(websocket)
        except Exception as e:
            self.log(f"[WS][FATAL] websocket_handler crashed", error=e, block="main_try")
            try:
                await websocket.close(reason="handler crash")
            except:
                pass

    async def _websocket_handler_core(self, websocket):
        try:

            ip = getattr(websocket, "remote_address", None)
            if isinstance(ip, tuple):
                ip = ip[0]
            else:
                ip = "unknown"
            self.log(f"[WS][CONNECT] Client connected from IP: {ip}")

            cert_bin = websocket.transport.get_extra_info("peercert", default=None)

            if not cert_bin:
                self.log(
                    f"[WS][NO CLIENT CERT] No client certificate presented by IP {ip} — cannot perform SPKI pin check")
                await websocket.close(reason="No client cert for SPKI verification")
                return

            # Explicitly confirm the client is in allowlist (or no allowlist restriction)
            if self.allowlist_ips:
                if ip not in self.allowlist_ips:
                    self.log(f"[WS][SECURITY] IP {ip} explicitly blocked by allowlist")
                    await websocket.close(reason="Blocked by IP allowlist")
                    return
                else:
                    self.log(f"[WS][SECURITY] IP {ip} explicitly allowed by allowlist")
            else:
                self.log("[WS][SECURITY] No IP allowlist restriction in place")

            # Confirm explicitly SSL transport details
            ssl_object = websocket.transport.get_extra_info('ssl_object')
            if ssl_object:
                cipher = ssl_object.cipher()
                peercert = ssl_object.getpeercert()
                self.log(f"[WS][TLS DETAILS] Cipher={cipher}, PeerCert={peercert}")
            else:
                self.log("[WS][HANDSHAKE ERROR] No SSL object found post-handshake")
                await websocket.close(reason="SSL handshake failed")
                return

            self._websocket_clients.add(websocket)

            self.log("[WS][CLIENT] Explicitly added client successfully. Ready for messages.")

            try:
                handshake = await asyncio.wait_for(websocket.recv(), timeout=5)
                hello = json.loads(handshake)
                if hello.get("type") == "hello" and "session_id" in hello:

                    if "sig" not in hello:
                        await websocket.close(reason="missing signature")
                        return
                    try:
                        crypto_utils.verify_signed_payload(hello, hello["sig"], self.peer_pub_key)
                        self.log(f"[WS][HELLO] signature accepted")
                    except Exception as e:
                        self.log(f"[WS][HELLO][DENY] Bad signature: {e}")
                        await websocket.close(reason="bad hello signature")
                        return

                    sid = hello["session_id"]
                    websocket.session_id = sid
                    self._sessions[sid] = {
                        "ws": websocket,
                        "agent": hello.get("agent"),
                        "started": time.time()
                    }

                    async def ping_keepalive(ws, sid):
                        while sid in self._sessions:
                            try:
                                await ws.ping()
                            except Exception:
                                break
                            await asyncio.sleep(10)

                    self.loop.create_task(ping_keepalive(websocket, sid))

                    self.update_broadcast_flag(session_id=sid)
                    self.log(f"[WS][SESSION] Bound to session_id={sid}")
                else:
                    self.log("[WS][SESSION][WARN] Invalid hello packet, closing.")
                    await websocket.close(reason="missing session_id")
                    return
            except Exception as e:
                self.log(f"[WS][SESSION][ERROR] Handshake failed: {e}")
                await websocket.close(reason="handshake failed")
                return

            while True:
                try:
                    raw = await websocket.recv()
                    self.log(f"[WS][MESSAGE RECEIVED] {raw}")

                    outer = json.loads(raw)

                    sig_b64 = outer.get("sig")
                    inner = outer.get("content", {})

                    try:
                        crypto_utils.verify_signed_payload(inner, sig_b64, self.peer_pub_key)
                        data = inner
                        self.log(f"[WS][HELLO] signature accepted")
                    except Exception as e:
                        self.log(f"[WS][SIG DENY] {e}")
                        await websocket.close(reason="bad message signature")
                        break

                    # Explicit echo acknowledgment
                    await websocket.send(json.dumps({
                        "type": "ack",
                        "echo": data
                    }))

                except websockets.ConnectionClosed as cc:
                    self.log(f"[WS][DISCONNECT] Explicit graceful disconnect ({cc.code}): {cc.reason}")
                    break
                except json.JSONDecodeError:
                    self.log("[WS][ERROR] Explicit malformed JSON received.")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Malformed JSON"
                    }))
                except Exception as e:
                    self.log(f"[WS][ERROR] Unexpected error explicitly: {e}")
                    break

        except Exception as e:
            self.log(f"[WS][FATAL] Explicit WebSocket handshake exception: {e}")
            await websocket.close(reason="Internal WebSocket exception")



        finally:

            self._websocket_clients.discard(websocket)
            if hasattr(websocket, "session_id"):
                sid = websocket.session_id
                if sid in self._sessions:
                    self._sessions.pop(sid, None)
                    self.update_broadcast_flag(session_id=sid, remove=True)
            self.log(f"[WS][CLEANUP] Client removed. Active={len(self._websocket_clients)}")

    def update_broadcast_flag(self, session_id=None, remove=False):
        base = os.path.join(self.path_resolution["comm_path_resolved"], "broadcast")
        os.makedirs(base, exist_ok=True)

        flag = os.path.join(base, f"connected.flag.{session_id}") if session_id else os.path.join(base, "connected.flag")

        if remove:
            if os.path.exists(flag):
                os.remove(flag)
            return

        open(flag, "w").close()
        os.utime(flag, None)

    def cmd_rpc_route(self, content, packet, identity:IdentityObject = None):
        try:
            self.log("Incoming routed RPC packet.")
            self.cmd_broadcast(content, content)
            #self.log(f"Routed response_id={content.get('response_id')} status={content.get('status')}")
        except Exception as e:
            self.log(error=e)  # Optional: write full trace to logs

    def cmd_send_alert_msg(self, content, packet, identity:IdentityObject = None):
        try:
            # Format the alert message
            msg = content.get("formatted_msg") or content.get("msg") or "[SWARM] Alert received."

            # Construct GUI-style feed packet
            broadcast_packet = {
                "handler": "cmd_alert_to_gui",
                "origin": content.get("origin", "unknown"),
                "timestamp": time.time(),
                "content": {
                    "msg": msg,
                    "level": content.get("level", "info"),
                    "origin": content.get("origin", "unknown"),
                    "formatted_msg": msg
                }
            }

            # Dispatch it via WebSocket
            self.cmd_broadcast(broadcast_packet["content"], broadcast_packet)

            self.log("Alert message sent to GUI feed.")
        except Exception as e:
            self.log(error=e)  # Optional: write full trace to logs


    # --- Helper: stable canonical JSON (no whitespace, sorted keys)
    @staticmethod
    def _canon(obj: dict) -> bytes:
        return json.dumps(obj or {}, separators=(",", ":"), sort_keys=True).encode()

    @staticmethod
    def _now() -> float:
        return time.time()

    def _sign_content(self, content: dict) -> str:
        """
        Returns base64 RS256 signature over canonicalized content.
        """
        if not self.ws_priv:
            return ""
        h = SHA256.new(self._canon(content))
        sig = pkcs1_15.new(self.ws_priv).sign(h)
        return base64.b64encode(sig).decode()


    def cmd_alert_to_gui(self, content, packet, identity:IdentityObject = None):
        self.log(f"Dispatching alert to GUI: {content}")
        self.cmd_broadcast(content, packet)

    def cmd_hive_log_delivery(self, content, packet, identity=None):
        uid = content.get("universal_id")
        num_lines = content.get("lines", 500)
        log_path = os.path.join(self.path_resolution["comm_path"], uid, "logs", "agent.log")

        if not os.path.exists(log_path):
            self.log(f"[LOG-DELIVERY] ❌ Log file not found: {uid}")
            return

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                raw_lines = f.readlines()[-num_lines:]

            emoji_map = {
                "INFO": "🔹",
                "ERROR": "❌",
                "DEBUG": "🐞",
                "WARNING": "⚠️"
            }

            final_lines = []
            for line in raw_lines:
                try:
                    entry = json.loads(line)
                    lvl = entry.get("level", "INFO")
                    ts = entry.get("timestamp", "?")
                    msg = entry.get("message", line.strip())
                    emoji = emoji_map.get(lvl.upper(), "🔸")
                    final_lines.append(f"{emoji} [{ts}] [{lvl}] {msg}")
                except:
                    final_lines.append(f"[MALFORMED] {line.strip()}")

            payload = {
                "handler": "phoenix.rpc_result.file_log_display",
                "content": {
                    "universal_id": uid,
                    "log": "\n".join(final_lines)
                }
            }

            self.cmd_broadcast(payload, packet)
            self.log(f"[LOG-DELIVERY] 📤 Broadcast log for {uid} to GUI.")

        except Exception as e:
            self.log(f"[LOG-DELIVERY][ERROR] Failed to send log: {e}")


    def decrypt_log_line(line, key_bytes):
        try:
            blob = base64.b64decode(line.strip())
            nonce, tag, ciphertext = blob[:12], blob[12:28], blob[28:]
            cipher = AES.new(key_bytes, AES.MODE_GCM, nonce=nonce)
            return cipher.decrypt_and_verify(ciphertext, tag).decode()
        except Exception as e:
            return f"[DECRYPT-FAIL] {str(e)}"

    def cmd_broadcast(self, content, packet, identity:IdentityObject = None):

        try:

            if not hasattr(self, "loop") or self.loop is None:
                self.log("[WS][REFLEX][SKIP] Event loop not ready.")
                return

            if not getattr(self, "websocket_ready", False):
                self.log("[WS][REFLEX][WAITING] Socket not bound.")
                return

            if self.debug.is_enabled():
                self.log(f"[WS][REFLEX]{packet}")

            data = json.dumps(packet, separators=(",", ":"), sort_keys=False)

            dead = []
            for client in self._websocket_clients:
                try:
                    asyncio.run_coroutine_threadsafe(client.send(data), self.loop)
                except Exception:
                    dead.append(client)

            for c in dead:
                self._websocket_clients.discard(c)

            self.log(f"Broadcasted to {len(self._websocket_clients)} clients.")
        except Exception as e:
            self.log(error=e)

if __name__ == "__main__":
    agent = Agent()
    agent.boot()