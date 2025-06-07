#Authored by Daniel F MacDonald and ChatGPT

import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

from flask import Response
from flask import Flask, request, jsonify
import ssl
import json
import threading
import time
import base64

from core.boot_agent import BootAgent
from core.class_lib.packet_delivery.utility.encryption.config import ENCRYPTION_CONFIG

from Cryptodome.Cipher import AES


class Agent(BootAgent):
    def __init__(self):
        super().__init__()

        self.app = Flask(__name__)
        self.port = 65431
        self.payload_dir = os.path.join(self.path_resolution['comm_path'], "matrix", "payload")
        self.cert_path = os.path.join(self.path_resolution['root_path'], "certs", "server.crt")
        self.key_path = os.path.join(self.path_resolution['root_path'], "certs", "server.key")
        self.client_ca = os.path.join(self.path_resolution['root_path'], "certs", "client.crt")
        self.configure_routes()

    def pre_boot(self):
        self.log("[PRE-BOOT] Matrix HTTPS Agent preparing routes and scanner.")
        threading.Thread(target=self.run_server, daemon=True).start()

    def post_boot(self):
        self.log("[POST-BOOT] Matrix HTTPS Agent ready and active.")

    def process_command(self, data):
        self.log(f"[CMD] Received delegated command: {data}")

    def cert_exists(self):
        return os.path.exists(self.cert_path) and os.path.exists(self.key_path)

    def worker_pre(self):
        self.log("[MATRIX_HTTPS] Boot initialized. Port online, certs verified.")

    def worker_post(self):
        self.log("[MATRIX_HTTPS] HTTPS interface shutting down. The swarm will feel it.")

    def configure_routes(self):

        # matrix_https.py (inside MatrixHTTPS class)

        @self.app.route("/agents", methods=["GET"])
        def get_agent_list():
            try:
                self.log("[CMD] Getting Live Agent List")
                comm_path = self.path_resolution['comm_path']
                agents = []

                if os.path.exists(comm_path):
                    for name in os.listdir(comm_path):
                        path = os.path.join(comm_path, name)
                        if name.lower().startswith("new folder") or name.startswith("."):
                            continue
                        if os.path.isdir(path) and os.path.exists(os.path.join(path, "agent_tree.json")):
                            agents.append(name)

                return jsonify({"status": "ok", "agents": sorted(agents)})

            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 500

        @self.app.route("/matrix/ping", methods=["GET"])
        def ping():
            return jsonify({"status": "ok"}), 200

        @self.app.route("/matrix", methods=["POST"])
        def receive_command():
            try:
                ip = request.remote_addr or "unknown"
                self.log(f"[MATRIX-HTTPS][SOURCE-IP] Packet received from {ip}")
                payload = request.get_json()
                ctype = payload.get("handler")
                content = payload.get("content", {})
                timestamp = payload.get("timestamp", time.time())

                self.log(f"[MATRIX-HTTPS][RECEIVED] {ctype} from {ip} → {content}")

                # === 1. Matrix-HTTPS native commands ===
                if ctype == "cmd_get_log":
                    uid = content.get("universal_id")
                    if not uid:
                        return jsonify({"status": "error", "message": "Missing universal_id"}), 400

                    log_path = os.path.join(self.path_resolution["comm_path"], uid, "logs", "agent.log")

                    if os.path.exists(log_path):
                        try:
                            key_bytes = None
                            if ENCRYPTION_CONFIG.is_enabled():
                                swarm_key = ENCRYPTION_CONFIG.get_swarm_key()
                                key_bytes = base64.b64decode(swarm_key)

                            rendered_lines = []

                            with open(log_path, "r") as f:
                                for line in f:
                                    try:
                                        if key_bytes:
                                            line = decrypt_log_line(line, key_bytes)

                                        entry = json.loads(line)
                                        ts = entry.get("timestamp", "?")
                                        lvl = entry.get("level", "INFO")
                                        msg = entry.get("message", "")
                                        emoji = {
                                            "INFO": "🔹", "ERROR": "❌", "WARNING": "⚠️", "DEBUG": "🐞"
                                        }.get(lvl.upper(), "🔸")
                                        rendered_lines.append(f"{emoji} [{ts}] [{lvl}] {msg}")
                                    except Exception as e:
                                        rendered_lines.append(f"[MALFORMED] {line.strip()}")

                            #output = "\n".join(rendered_lines[-250:])
                            output = "\n".join(rendered_lines)
                            self.log(f"[LOG-DELIVERY] ✅ Sent {len(rendered_lines)} lines for {uid}")
                            return Response(
                                json.dumps({"status": "ok", "log": output}, ensure_ascii=False),
                                status=200,
                                mimetype="application/json"
                            )

                        except Exception as e:
                            self.log(f"[HTTPS-LOG][ERROR] Could not process log for {uid}: {e}")
                            return jsonify({"status": "error", "message": str(e)}), 500



                elif ctype == "cmd_list_tree":

                    try:

                        tree_path = {

                            "path": self.path_resolution["comm_path"],

                            "address": "matrix",

                            "drop": "directive",

                            "name": "agent_tree_master.json"

                        }

                        tp = self.load_directive(tree_path)

                        if not tp or not hasattr(tp, "root"):
                            return jsonify(
                                {"status": "error", "message": "Failed to load directive or invalid tree."}), 500

                        return jsonify({"status": "ok", "tree": tp.root}), 200


                    except Exception as e:

                        self.log(f"[LIST_TREE][ERROR] {str(e)}")

                        return jsonify({"status": "error", "message": str(e)}), 500

                elif ctype == "cmd_ping":
                    return jsonify({"status": "ok"}), 200

                # === 2. All other commands go to Matrix ===
                target = "matrix"

                payload['origin'] = self.command_line_args['universal_id']

                pk = self.get_delivery_packet("standard.command.packet", new=True)
                pk.set_data(payload)

                pk2 = self.get_delivery_packet("standard.general.json.packet", new=True)

                pk.set_packet(pk2,"content")

                da = self.get_delivery_agent("file.json_file", new=True)

                da.set_location({"path": self.path_resolution["comm_path"]}) \
                    .set_address([target]) \
                    .set_drop_zone({"drop": "incoming"}) \
                    .set_packet(pk) \
                    .deliver()

                self.log(f"##################{da.get_saved_filename()}{pk.get_packet()}***********************")


                self.log(f"[MATRIX-HTTPS][FORWARDED] {ctype} → {da.get_saved_filename()}")
                return jsonify({"status": "ok", "message": f"{ctype} routed to Matrix"})

            except Exception as e:
                self.log(f"[MATRIX-HTTPS][ERROR] {e}")

        def threaded_log_response(self, uid, client_response):
            try:
                log_path = os.path.join(self.path_resolution["comm_path"], uid, "logs", "agent.log")

                if not os.path.exists(log_path):
                    return client_response({"status": "error", "message": "Log not found"}, 404)

                key_bytes = None
                if ENCRYPTION_CONFIG.is_enabled():
                    swarm_key = ENCRYPTION_CONFIG.get_swarm_key()
                    key_bytes = base64.b64decode(swarm_key)

                rendered_lines = []

                with open(log_path, "r") as f:
                    for line in f:
                        try:
                            if key_bytes:
                                line = self.decrypt_log_line(line, key_bytes)
                            entry = json.loads(line)
                            ts = entry.get("timestamp", "?")
                            lvl = entry.get("level", "INFO")
                            msg = entry.get("message", "")
                            emoji = {"INFO": "🔹", "ERROR": "❌", "WARNING": "⚠️", "DEBUG": "🐞"}.get(lvl.upper(), "🔸")
                            rendered_lines.append(f"{emoji} [{ts}] [{lvl}] {msg}")
                        except Exception:
                            rendered_lines.append(f"[MALFORMED] {line.strip()}")

                output = "\n".join(rendered_lines)
                self.log(f"[LOG-DELIVERY] ✅ Sent {len(rendered_lines)} lines for {uid}")
                return client_response({"status": "ok", "log": output}, 200)

            except Exception as e:
                self.log(f"[HTTPS-LOG][ERROR] Could not process log for {uid}: {e}")
                return client_response({"status": "error", "message": str(e)}, 500)

        def decrypt_log_line(self, line, key_bytes):
            try:
                blob = base64.b64decode(line.strip())
                nonce, tag, ciphertext = blob[:12], blob[12:28], blob[28:]
                cipher = AES.new(key_bytes, AES.MODE_GCM, nonce=nonce)
                return cipher.decrypt_and_verify(ciphertext, tag).decode()
            except Exception as e:
                return f"[DECRYPT-FAIL] {str(e)}"

    def run_server(self):
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

        context.load_verify_locations(cafile="https_certs/rootCA.pem")
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_cert_chain(certfile="https_certs/server.fullchain.crt", keyfile="https_certs/server.key")
        self.log(f"[HTTPS] Listening on port {self.port}")
        self.app.run(host="0.0.0.0", port=self.port, ssl_context=context)

if __name__ == "__main__":
    agent = Agent()
    agent.boot()