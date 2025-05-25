#Authored by Daniel F MacDonald and ChatGPT

import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))


from flask import Flask, request, jsonify
import ssl
import json
import threading
import time

from core.boot_agent import BootAgent

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
                payload = request.get_json()
                ctype = payload.get("type")
                content = payload.get("content", {})
                timestamp = payload.get("timestamp", time.time())

                self.log(f"[MATRIX-HTTPS][RECEIVED] {ctype} → {content}")

                # === 1. Matrix-HTTPS native commands ===
                if ctype == "get_log":
                    uid = content.get("universal_id")
                    if not uid:
                        return jsonify({"status": "error", "message": "Missing universal_id"}), 400

                    log_path = os.path.join(self.path_resolution["comm_path"], uid, "logs", "agent.log")
                    if os.path.exists(log_path):
                        try:
                            with open(log_path, "r", errors="ignore") as f:  # Ignore encoding issues
                                lines = f.readlines()[-100:]  # Return the last 100 lines (prevent memory overload)
                                return jsonify({"status": "ok", "log": "".join(lines)}), 200
                        except Exception as e:
                            return jsonify({"status": "error", "message": str(e)}), 500

                    return jsonify({"status": "error", "message": f"Log not found for {uid}"}), 404

                elif ctype == "list_tree":
                    tree_path = os.path.join(self.path_resolution["comm_path"], "matrix", "agent_tree_master.json")
                    if os.path.exists(tree_path):
                        with open(tree_path) as f:
                            return jsonify({"status": "ok", "tree": json.load(f)})
                    return jsonify({"status": "error", "message": "agent_tree_master.json not found"}), 404

                elif ctype == "ping":
                    return jsonify({"status": "ok"}), 200

                # === 2. All other commands go to Matrix ===
                target = "matrix"
                target_dir = os.path.join(self.path_resolution["comm_path"], target, "incoming")
                os.makedirs(target_dir, exist_ok=True)

                fname = f"{ctype}_{int(timestamp)}.cmd"
                fpath = os.path.join(target_dir, fname)

                with open(fpath, "w") as f:
                    json.dump(payload, f, indent=2)

                self.log(f"[MATRIX-HTTPS][FORWARDED] {ctype} → {fpath}")
                return jsonify({"status": "ok", "message": f"{ctype} routed to Matrix"})

            except Exception as e:
                self.log(f"[MATRIX-HTTPS][ERROR] {e}")
                return jsonify({"status": "error", "message": str(e)}), 500

        def receive_commasdfsdfsdnd():

            try:
                payload = request.get_json()
                self.log(f"[CMD] Received HTTPS command: {payload}")
                ctype = payload.get("type")
                content = payload.get("content", {})

                self.log(f"[DEBUG] Incoming inject content: {content}")

                self.log(f"[MATRIX_HTTPS][PAYLOAD] Received command: {payload}")

                if ctype == "spawn":
                    self.log(f"'[MATRIX_HTTPS][PAYLOAD] Received Spawn command. Payload: ' {payload}")
                    #from core.core_spawner import spawn_agent
                    #spawn_agent("matrix", str(uuid.uuid4()), content.get("agent_name"), content.get("universal_id"), "gui", directive=content)
                    print('[MATRIX_HTTPS][PAYLOAD] Received Spawn command')
                elif ctype == "inject":
                    self.log(f"[MATRIX-HTTPS][CMD][INJECTING] {payload}")
                    #id of agent that the new agent will be a child of, must be in tree
                    target_universal_id = content.get("target_universal_id")
                    #id of new agent, which must be unique though the whole tree
                    universal_id = content.get("universal_id")
                    #agent file to clone
                    agent_name = content.get("agent_name")

                    delegated = content.get("delegated", [])


                    if universal_id and agent_name:

                        directive = {
                            "target_universal_id": target_universal_id,
                            "universal_id": universal_id,
                            "agent_name": agent_name,
                            "delegated": delegated
                        }

                        inject_payload = {
                            "type": "inject",
                            "timestamp": time.time(),
                            "content": directive
                        }

                        #FILENAME OF COMMAND TO MATRIX
                        fname = f"inject_{agent_name}_{int(time.time())}.json"

                        fpath = os.path.join(self.payload_dir, fname)

                        with open(fpath, "w") as f:

                            json.dump(inject_payload, f, indent=2)

                        self.log(f"[INJECT] Payload dropped to Matrix: {fpath}")
                        return jsonify({"status": "ok", "message": f"{agent_name} inject routed to Matrix"})
                    else:
                        return jsonify({"status": "error", "message": "Missing universal_id or agent_name"}), 400

                elif ctype == "inject_team":
                    target_universal_id = content.get("target_universal_id")
                    subtree = content.get("subtree")

                    if not target_universal_id or not subtree:
                        return jsonify({"status": "error", "message": "Missing target_universal_id or subtree"}), 400

                    inject_payload = {
                        "type": "inject_team",
                        "timestamp": time.time(),
                        "content": {
                            "target_universal_id": target_universal_id,
                            "subtree": subtree
                        }
                    }

                    fname = f"inject_team_{int(time.time())}.json"
                    fpath = os.path.join(self.payload_dir, fname)

                    with open(fpath, "w") as f:
                        json.dump(inject_payload, f, indent=2)

                    self.log(f"[INJECT_TEAM] Payload dropped to Matrix: {fpath}")
                    return jsonify({"status": "ok", "message": f"Team injected under {target_universal_id}"})


                elif ctype == "replace_agent":

                    full_payload = {

                        "type": "replace_agent",

                        "timestamp": time.time(),

                        "content": content

                    }

                    fname = f"replace_agent_{int(time.time())}.json"

                    fpath = os.path.join(self.payload_dir, fname)

                    with open(fpath, "w") as f:

                        json.dump(full_payload, f, indent=2)

                    self.log(f"[REPLACE_AGENT] Payload routed to Matrix: {fpath}")

                    return jsonify({"status": "ok", "message": "replace_agent queued for Matrix"})

                elif ctype == "stop":
                    content = payload.get("content", {})
                    targets = content.get("targets", [])
                    if isinstance(targets, str):
                        targets = [targets]

                    # Build stop payload to drop into Matrix's payload queue
                    payload = {
                        "type": "stop",
                        "timestamp": time.time(),
                        "content": {
                            "targets": targets
                        }
                    }

                    inbox = os.path.join(self.path_resolution["comm_path"], "matrix", "payload")
                    os.makedirs(inbox, exist_ok=True)

                    fname = f"stop_{int(time.time())}.json"
                    fpath = os.path.join(inbox, fname)

                    with open(fpath, "w") as f:
                        json.dump(payload, f, indent=2)

                    self.log(f"[MATRIX-HTTPS][PAYLOAD-CMD][STOP-AGENT] Payload dropped to Matrix: {fpath}")
                    return jsonify({"status": "ok", "message": f"Agent sent stop under {targets}"})

                elif ctype == "resume":
                    targets = content.get("targets", [])
                    if isinstance(targets, str):
                        targets = [targets]

                    for universal_id in targets:
                        die_path = os.path.join(self.path_resolution["comm_path"], universal_id, "incoming", "die")
                        tombstone_path = os.path.join(self.path_resolution["comm_path"], universal_id, "incoming",
                                                      "tombstone")

                        if os.path.exists(die_path):
                            os.remove(die_path)
                            self.log(f"[MATRIX][RESUME] Removed die file for {universal_id}")

                        if os.path.exists(tombstone_path):
                            os.remove(tombstone_path)
                            self.log(f"[MATRIX][RESUME] Removed tombstone for {universal_id}")


                elif ctype == "shutdown_subtree":
                    target_id = content.get("universal_id")
                    if not target_id:
                        return jsonify({"status": "error", "message": "Missing universal_id"}), 400
                    try:

                        from core.tree_parser import TreeParser
                        tree_path = os.path.join(self.path_resolution["comm_path"], "matrix", "agent_tree_master.json")
                        tp = TreeParser.load_tree(tree_path)
                        subtree_ids = tp.get_subtree_nodes(target_id)

                        for agent_id in subtree_ids:
                            die_path = os.path.join(self.path_resolution["comm_path"], agent_id, "incoming", "die")
                            os.makedirs(os.path.dirname(die_path), exist_ok=True)
                            with open(die_path, "w") as f:
                                f.write("☠️")

                        self.log(f"[MATRIX-HTTPS][SHUTDOWN] Issued die to subtree under: {target_id}")
                        return jsonify(
                            {"status": "ok", "message": f"Shutdown signal sent to {len(subtree_ids)} agents"})

                    except Exception as e:
                        self.log(f"[ERROR][SHUTDOWN_SUBTREE] {str(e)}")
                        return jsonify({"status": "error", "message": str(e)}), 500

                elif ctype == "restart_subtree":
                    target_id = content.get("universal_id")
                    if not target_id:
                        return jsonify({"status": "error", "message": "Missing universal_id"}), 400

                    try:
                        from core.tree_parser import TreeParser
                        tree_path = os.path.join(self.path_resolution["comm_path"], "matrix", "agent_tree_master.json")
                        tp = TreeParser.load_tree(tree_path)
                        subtree_ids = tp.get_subtree_nodes(target_id)

                        for agent_id in subtree_ids:
                            die_path = os.path.join(self.path_resolution["comm_path"], agent_id, "incoming", "die")
                            tombstone_path = os.path.join(self.path_resolution["comm_path"], agent_id, "incoming",
                                                          "tombstone")

                            if os.path.exists(die_path):
                                os.remove(die_path)
                                self.log(f"[MATRIX-HTTPS][RESUME] Removed die signal for {agent_id}")

                            if os.path.exists(tombstone_path):
                                os.remove(tombstone_path)
                                self.log(f"[MATRIX-HTTPS][RESUME] Removed tombstone for {agent_id}")

                        self.log(f"[MATRIX-HTTPS][RESTART_SUBTREE] Resumed {len(subtree_ids)} agents under {target_id}")
                        return jsonify(
                            {"status": "ok", "message": f"Resumed {len(subtree_ids)} agents under {target_id}."})

                    except Exception as e:
                        self.log(f"[MATRIX-HTTPS][ERROR] Restart Subtree: {str(e)}")
                        return jsonify({"status": "error", "message": str(e)}), 500

                elif ctype in {"restart_subtree", "delete_node", "delete_subtree"}:
                    payload = {
                        "type": ctype,
                        "timestamp": time.time(),
                        "content": content
                    }
                    fname = f"{ctype}_{int(time.time())}.json"
                    fpath = os.path.join(self.payload_dir, fname)

                    with open(fpath, "w") as f:
                        json.dump(payload, f, indent=2)

                    self.log(f"[MATRIX-HTTPS][QUEUED] {ctype} → {fpath}")
                    return jsonify({"status": "ok", "message": f"{ctype} routed to Matrix"})


                elif ctype == "get_log":
                    self.log(f"[MATRIX-HTTPS][CMD][GET-LOG] {payload}")
                    universal_id = content.get("universal_id")
                    if not universal_id:
                        return jsonify({"status": "error", "message": "Missing universal_id"}), 400

                    log_path = os.path.join(self.path_resolution["comm_path"], universal_id, "logs", "agent.log")

                    if os.path.exists(log_path):
                        try:
                            with open(log_path, "r") as f:
                                logs = f.read()
                            return jsonify({"status": "ok", "log": logs})
                        except Exception as e:
                            self.log(f"[HTTPS-LOG] Error reading log: {e}")
                            return jsonify({"status": "error", "message": str(e)}), 500
                    else:
                        self.log(f"[HTTPS-LOG] Log not found for {universal_id}")
                        return jsonify({"status": "error", "message": f"No log found for {universal_id}"}), 404

                elif ctype == "list_tree":
                    tree_path = os.path.join(self.path_resolution["comm_path"], "matrix", "agent_tree_master.json")
                    if os.path.exists(tree_path):
                        with open(tree_path) as f:
                            data = json.load(f)
                        return jsonify({"status": "ok", "tree": data})
                    else:
                        return jsonify({"status": "error", "message": "agent_tree_master.json not found"}), 404

                elif ctype == "kill":
                    payload_path = os.path.join(self.payload_dir, f"kill_{int(time.time())}.json")
                    with open(payload_path, "w") as f:
                        json.dump(payload, f, indent=2)
                        return jsonify({"status": "ok", "message": f"Kill payload routed to Matrix"})


                else:

                    # Fallback: drop ANY unrecognized payload into Matrix's payload dir

                    fallback_name = f"cmd_{ctype}_{int(time.time())}.json"

                    fallback_path = os.path.join(self.payload_dir, fallback_name)

                    with open(fallback_path, "w") as f:

                        json.dump(payload, f, indent=2)

                    self.log(f"[MATRIX-HTTPS][FALLBACK] Routed unknown command '{ctype}' to Matrix payload queue.")

                    return jsonify({"status": "ok", "message": f"Command '{ctype}' routed to Matrix."})

                return jsonify({"status": "ok", "message": f"Command {ctype} processed."})

            except Exception as e:

                self.log(f"[ERROR] Command handling failed: {str(e)}")

                return jsonify({"status": "error", "message": str(e)}), 500

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