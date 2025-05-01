#Authored by Daniel F MacDonald and ChatGPT
from flask import Flask, request, jsonify
import ssl
import os
import json
import threading
import time

from agent.core.boot_agent import BootAgent

class MatrixHTTPS(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.app = Flask(__name__)
        self.port = 65431
        self.payload_dir = os.path.join(path_resolution['comm_path'], "matrix", "payload")
        self.cert_path = os.path.join(path_resolution['root_path'], "certs", "server.crt")
        self.key_path = os.path.join(path_resolution['root_path'], "certs", "server.key")
        self.client_ca = os.path.join(path_resolution['root_path'], "certs", "client.crt")
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
                self.log(f"[CMD] Received HTTPS command: {payload}")
                ctype = payload.get("type")
                content = payload.get("content", {})

                self.log(f"[DEBUG] Incoming inject content: {content}")

                self.log(f"[MATRIX_HTTPS][PAYLOAD] Received command: {payload}")

                if ctype == "spawn":
                    self.log(f"'[MATRIX_HTTPS][PAYLOAD] Received Spawn command. Payload: ' {payload}")
                    #from agent.core.core_spawner import spawn_agent
                    #spawn_agent("matrix", str(uuid.uuid4()), content.get("agent_name"), content.get("permanent_id"), "gui", directive=content)
                    print('[MATRIX_HTTPS][PAYLOAD] Received Spawn command')
                elif ctype == "inject":
                    self.log(f"[MATRIX-HTTPS][CMD][INJECTING] {payload}")
                    #id of agent that the new agent will be a child of, must be in tree
                    target_perm_id = content.get("target_perm_id")
                    #id of new agent, which must be unique though the whole tree
                    perm_id = content.get("perm_id")
                    #agent file to clone
                    agent_name = content.get("agent_name")

                    delegated = content.get("delegated", [])


                    if perm_id and agent_name:

                        directive = {
                            "target_perm_id": target_perm_id,
                            "perm_id": perm_id,
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
                        return jsonify({"status": "error", "message": "Missing perm_id or agent_name"}), 400

                elif ctype == "inject_team":
                    target_perm_id = content.get("target_perm_id")
                    subtree = content.get("subtree")

                    if not target_perm_id or not subtree:
                        return jsonify({"status": "error", "message": "Missing target_perm_id or subtree"}), 400

                    inject_payload = {
                        "type": "inject_team",
                        "timestamp": time.time(),
                        "content": {
                            "target_perm_id": target_perm_id,
                            "subtree": subtree
                        }
                    }

                    fname = f"inject_team_{int(time.time())}.json"
                    fpath = os.path.join(self.payload_dir, fname)

                    with open(fpath, "w") as f:
                        json.dump(inject_payload, f, indent=2)

                    self.log(f"[INJECT_TEAM] Payload dropped to Matrix: {fpath}")
                    return jsonify({"status": "ok", "message": f"Team injected under {target_perm_id}"})

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

                    for perm_id in targets:
                        die_path = os.path.join(self.path_resolution["comm_path"], perm_id, "incoming", "die")
                        tombstone_path = os.path.join(self.path_resolution["comm_path"], perm_id, "incoming",
                                                      "tombstone")

                        if os.path.exists(die_path):
                            os.remove(die_path)
                            self.log(f"[MATRIX][RESUME] Removed die file for {perm_id}")

                        if os.path.exists(tombstone_path):
                            os.remove(tombstone_path)
                            self.log(f"[MATRIX][RESUME] Removed tombstone for {perm_id}")

                elif ctype == "shutdown_subtree":
                    target_id = content.get("perm_id")
                    if not target_id:
                        return jsonify({"status": "error", "message": "Missing perm_id"}), 400
                    try:

                        from agent.core.tree_parser import TreeParser
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
                    target_id = content.get("perm_id")
                    if not target_id:
                        return jsonify({"status": "error", "message": "Missing perm_id"}), 400

                    try:
                        from agent.core.tree_parser import TreeParser
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


                elif ctype == "delete_node":
                    self.log(f"[MATRIX-HTTPS][CMD][DELETE-NODE] {payload}")
                    self.tree.delete_node(content.get("perm_id"))
                elif ctype == "delete_subtree":
                    self.log(f"[MATRIX-HTTPS][CMD][DELETE-SUBTREE] {payload}")
                    self.tree.delete_subtree(content.get("perm_id"))
                elif ctype == "get_log":
                    self.log(f"[MATRIX-HTTPS][CMD][GET-LOG] {payload}")
                    perm_id = content.get("perm_id")
                    if not perm_id:
                        return jsonify({"status": "error", "message": "Missing perm_id"}), 400

                    log_path = os.path.join(self.path_resolution["comm_path"], perm_id, "logs", "agent.log")

                    if os.path.exists(log_path):
                        try:
                            with open(log_path, "r") as f:
                                logs = f.read()
                            return jsonify({"status": "ok", "log": logs})
                        except Exception as e:
                            self.log(f"[HTTPS-LOG] Error reading log: {e}")
                            return jsonify({"status": "error", "message": str(e)}), 500
                    else:
                        self.log(f"[HTTPS-LOG] Log not found for {perm_id}")
                        return jsonify({"status": "error", "message": f"No log found for {perm_id}"}), 404

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
                    return jsonify({"status": "error", "message": "Unknown command type."}), 400

                return jsonify({"status": "ok", "message": f"Command {ctype} processed."})



            except Exception as e:
                self.log(f"[CMD] Error processing command: {e}")
                return jsonify({"status": "error", "message": str(e)}), 500

            except Exception as e:

                self.log(f"[ERROR] Command handling failed: {str(e)}")

                return jsonify({"status": "error", "message": str(e)}), 500

    def run_server(self):
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

        context.load_verify_locations(cafile="certs/rootCA.pem")
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_cert_chain(certfile="certs/server.fullchain.crt", keyfile="certs/server.key")
        self.log(f"[HTTPS] Listening on port {self.port}")
        self.app.run(host="0.0.0.0", port=self.port, ssl_context=context)

if __name__ == "__main__":

    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))

    agent = MatrixHTTPS(path_resolution, command_line_args)

    agent.boot()
