#Authored by Daniel F MacDonald and ChatGPT aka The Generals
import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))
from flask import Response
from flask import Flask, request, jsonify
import threading
import time
import ssl
from Crypto.PublicKey import RSA
from matrixswarm.core.utils.crypto_utils import pem_fix
from werkzeug.serving import WSGIRequestHandler
from matrixswarm.core.utils.cert_loader import load_cert_chain_from_memory
from matrixswarm.core.boot_agent import BootAgent
from matrixswarm.core.utils.swarm_trustkit import extract_spki_pin_from_cert
from matrixswarm.core.class_lib.packet_delivery.utility.security.packet_size import guard_packet_size
from matrixswarm.core.utils import crypto_utils
from matrixswarm.core.utils.swarm_sleep import interruptible_sleep
from werkzeug.serving import make_server

class CustomRequestHandler(WSGIRequestHandler):
    def make_environ(self):
        environ = super().make_environ()
        try:
            client_cert = self.connection.getpeercert(binary_form=True)
            environ["peercert"] = client_cert
        except Exception:
            environ["peercert"] = None
        return environ

class Agent(BootAgent):
    def __init__(self):
        super().__init__()
        self.AGENT_VERSION = "2.0.0"
        self.app = Flask(__name__)
        self.port = 65431

        config = self.tree_node.get("config", {})
        self.allowlist_ips = config.get("allowlist_ips", [])

        self.payload_dir = os.path.join(self.path_resolution['comm_path'], "matrix", "payload")

        try:
            security = self.tree_node.get("config", {}).get("security", {}) or {}
            conn = security.get("connection", {}) or {}

            server_cert = conn.get("server_cert", {}) or {}
            client_cert = conn.get("client_cert", {}) or {}
            ca_root = conn.get("ca_root", {}) or {}

            # Load our server TLS cert & key
            cert_pem = server_cert.get("cert")
            key_pem = server_cert.get("key")
            ca_pem = ca_root.get("cert")

            if not cert_pem or not key_pem:
                raise ValueError("Missing server TLS cert/key in connection.server_cert")

            # Store in-memory PEMs
            self.cert_pem = pem_fix(cert_pem)
            self.key_pem = pem_fix(key_pem)
            self.ca_pem = pem_fix(ca_pem) if ca_pem else None

            # Compute local SPKI pin for diagnostics (optional)
            try:
                self.local_spki = extract_spki_pin_from_cert(self.cert_pem.encode())
            except Exception as e:
                self.local_spki = None
                self.log("[HTTPS][SPKI][WARN] Could not compute local SPKI pin", error=e)

            # Optionally track expected client SPKI pin (not enforced)
            self.expected_peer_spki = client_cert.get("spki_pin")

            # Optionally load remote_pubkey for packet signature auth
            signing_cfg = security.get("signing", {})
            peer_pub_pem = signing_cfg.get("remote_pubkey")
            self.peer_pub_key = RSA.import_key(peer_pub_pem.encode()) if peer_pub_pem else None

            # Baseline process liveness
            self._emit_process_beacon = self.check_for_thread_poke(
                "https_process", timeout=60, emit_to_file_interval=10
            )

            # True service liveness
            self._emit_beacon = self.check_for_thread_poke(
                "https_service", timeout=60, emit_to_file_interval=10
            )
            self.log("[CERT-LOADER] In-memory TLS certs loaded successfully.")
            self.configure_routes()


        except Exception as e:
            self.log("[CERT-LOADER][FATAL] Failed to load certs from directive", error=e, block="init")
            time.sleep(2)
            self.run_server_retries = False

        self.local_tree_root = None
        # keep trying to start for infinity: false do max retries in method
        self.run_server_retries = False
        self._last_dir_request = 0
        self._emit_beacon = self.check_for_thread_poke("worker", timeout=60, emit_to_file_interval=10)

    def pre_boot(self):
        self.log("[PRE-BOOT] Matrix HTTPS Agent preparing routes and scanner.")
        threading.Thread(target=self.run_server, daemon=True).start()

    def post_boot(self):
        self.log(f"{self.NAME} v{self.AGENT_VERSION} – perimeter guard up.")


    def process_command(self, data):
        self.log(f"[CMD] Received delegated command: {data}")

    def worker_pre(self):
        self.log("[MATRIX_HTTPS] Boot initialized. Port online, certs verified.")

    def service_monitor(self):
        """Continuously self-ping Flask /ping route to prove HTTPS stack health."""
        while self.running:
            try:
                with self.app.test_client() as client:
                    resp = client.get("/ping")
                    if resp.status_code == 200:
                        self._emit_beacon()
                    else:
                        self.log(f"[MATRIX-HTTPS][ERROR] Ping route unhealthy: {resp.status_code}")
            except Exception as e:
                self.log("[MATRIX-HTTPS][ERROR] Internal ping failed", error=e)
            interruptible_sleep(self, 30)

    def worker_post(self):
        self.log("[MATRIX_HTTPS] HTTPS interface shutting down. The swarm will feel it.")

    def configure_routes(self):

        @self.app.route("/ping", methods=["GET"])
        def ping():
            return jsonify({"status": "ok"}), 200

        @self.app.route("/matrix", methods=["POST"])
        def receive_command():
            try:
                ip = request.remote_addr or "unknown"

                # 0) IP allowlist gate
                if self.allowlist_ips and ip not in self.allowlist_ips:
                    self.log(f"[MATRIX-HTTPS][BLOCKED] IP not allowed: {ip}")
                    return jsonify({"status": "error", "message": "Access denied"}), 403

                # 1) TLS client-cert SPKI pin (bind transport to expected peer)
                cert_bin = request.environ.get("peercert", None)
                if not cert_bin or not self.expected_peer_spki:
                    return jsonify({"status": "denied", "message": "missing peer cert or pin"}), 403

                actual_pin = extract_spki_pin_from_cert(cert_bin)
                if actual_pin != self.expected_peer_spki:
                    self.log(f"[HTTPS][SPKI DENY] got {actual_pin}, expected {self.expected_peer_spki}")
                    return jsonify({"status": "denied", "message": "SPKI mismatch"}), 403

                # 2) Parse JSON
                outer = request.get_json(silent=True, force=True) or {}
                sig_b64 = outer.get("sig")
                inner = outer.get("content", {})

                if not isinstance(inner, dict):
                    return jsonify({"status": "error", "message": "bad packet format"}), 400

                # 3) Size / structure guard on inner packet
                if not guard_packet_size(inner, log=self.log):
                    return jsonify({"status": "error", "message": "bad or oversized payload"}), 413

                handler = inner.get("handler")
                ts = inner.get("ts")

                # 4) Replay window
                try:
                    if not ts or abs(time.time() - float(ts)) > 120:
                        return jsonify({"status": "denied", "message": "stale"}), 403
                except Exception:
                    return jsonify({"status": "denied", "message": "bad timestamp"}), 403

                # 5) Signature verification over inner dict
                if not (self.peer_pub_key and sig_b64 and inner):
                    return jsonify({"status": "denied", "message": "missing signature or key"}), 403

                try:
                    crypto_utils.verify_signed_payload(inner, sig_b64, self.peer_pub_key)
                except Exception as e:
                    self.log(f"[HTTPS][SIG DENY] {e}")
                    return jsonify({"status": "denied", "message": "bad signature"}), 403

                # 6) All gates passed — relay to Matrix
                self.log(f"[MATRIX-HTTPS][RELAY] {handler} from {ip}")

                pk = self.get_delivery_packet("standard.command.packet", new=True)
                pk.set_data(inner)  # relay the verified inner command

                wrapper = self.get_delivery_packet("standard.general.json.packet", new=True)
                pk.set_packet(wrapper, "content")

                self.pass_packet(pk, target_uid="matrix")
                return jsonify({"status": "ok", "message": "Relayed to Matrix"})

            except Exception as e:
                self.log(f"[MATRIX-HTTPS][ERROR]", error=e, block="main_try")
                return jsonify({"status": "error", "message": str(e)}), 500

        @self.app.route("/matrix", methods=["GET", "PUT", "DELETE", "OPTIONS", "HEAD"])
        def deny_unsupported_methods():

            ip = request.remote_addr or "unknown"

            if self.allowlist_ips and ip not in self.allowlist_ips:
                self.log(f"[MATRIX-HTTPS][BLOCKED] Request from disallowed IP: {ip}")
                return jsonify({"status": "error", "message": "Access denied"}), 403

            self.log(f"[MATRIX-HTTPS][TRAP] Got {request.method} from {request.remote_addr}")
            return self.make_spoof_response()

        @self.app.route("/robots.txt", methods=["GET"])
        @self.app.route("/admin", methods=["GET"])
        @self.app.route("/wp-login.php", methods=["GET", "POST"])
        @self.app.route("/cgi-bin/", methods=["GET", "POST"])

        def trap_scan_targets():
            self.log(f"[MATRIX-HTTPS][SCAN-TRAP] Bait endpoint hit by {request.remote_addr}")
            return self.make_spoof_response()


    def make_spoof_response(self):

        msg = """<!DOCTYPE html>
                           <html>
                           <head>
                             <title>Nice Try</title>
                             <style>
                               body {
                                 background: black;
                                 color: #0f0;
                                 font-family: monospace;
                                 text-align: center;
                                 margin-top: 10vh;
                               }
                             </style>
                           </head>
                           <body>
                             <h1>🧠 Nice one, genius.</h1>
                             <p>This isn't a WordPress blog. It's a swarm fortress.</p>
                             <p>Consider this your official notification: you triggered the trap.</p>
                             <p><small>Matrix has logged your request.</small></p>
                           </body>
                           </html>
                           """
        return Response(msg, status=418, mimetype="text/html")  # 418 I'm a Teapot


    def shutdown_cleanup(self):
        import os
        for f in [getattr(self, "_cert_file", None), getattr(self, "_key_file", None), getattr(self, "_ca_file", None)]:
            try:
                if f and hasattr(f, "name") and os.path.exists(f.name):
                    os.unlink(f.name)
                    self.log(f"[CLEANUP] Deleted temp cert file: {f.name}")
            except Exception as e:
                self.log("[CLEANUP][ERROR] Failed to delete temp cert", error=e, block="shutdown")

    def run_server(self):
        retry_delay = 10
        max_retries = 5
        retries = 0

        while (retries < max_retries) or self.run_server_retries:
            try:
                self.log("[HTTPS] Starting run_server()...")

                context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                # Require client certs, but don't allow them to stall forever
                context.verify_mode = ssl.CERT_REQUIRED
                load_cert_chain_from_memory(context, self.cert_pem, self.key_pem)

                if self.ca_pem:
                    context.load_verify_locations(cadata=self.ca_pem)

                httpd = make_server(
                    "0.0.0.0",
                    self.port,
                    self.app,
                    ssl_context=context,
                    request_handler=CustomRequestHandler
                )

                # Limit how long handshakes can sit idle
                httpd.socket.settimeout(5)  # 5-second handshake window

                self.log(f"[HTTPS] Listening on port {self.port}")

                # Start process liveness thread
                def process_monitor():
                    while self.running:
                        self._emit_process_beacon()
                        interruptible_sleep(self, 30)

                # Run the HTTPS server loop in its own thread
                threading.Thread(target=httpd.serve_forever, daemon=True).start()

                # Watchdog threads
                threading.Thread(target=process_monitor, daemon=True).start()
                threading.Thread(target=self.service_monitor, daemon=True).start()

                break  # success

            except Exception as e:
                self.log(f"[HTTPS][FAIL] Server failed to start or crashed", error=e)
                retries += 1
                self.log(f"[HTTPS][RETRY] Attempt {retries}/{max_retries} in {retry_delay}s")
                time.sleep(retry_delay)
            finally:
                self.shutdown_cleanup()

        if retries >= max_retries:
            self.log("[HTTPS][ABORT] Max retries reached. Server not started.")

if __name__ == "__main__":
    agent = Agent()
    agent.boot()