import eventlet
eventlet.monkey_patch()

import threading
import os
import json
import time
import ssl
from flask import Flask
from flask_socketio import SocketIO
from agent.core.utils.swarm_sleep import interruptible_sleep
from agent.core.boot_agent import BootAgent

# Flask + SocketIO app
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

@app.route("/")
def index():
    return "MatrixSwarm WebSocket Streamer online."

@socketio.on('connect')
def handle_connect():
    print("[WS] Client connected")

@socketio.on('disconnect')
def handle_disconnect():
    print("[WS] Client disconnected")

class AlarmStreamerAgent(BootAgent):

    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)

        config = tree_node.get("config", {}) if 'tree_node' in globals() else {}
        self.alarm_path = os.path.join(self.path_resolution["comm_path"], "alarm", "incoming")
        os.makedirs(self.alarm_path, exist_ok=True)
        self.seen_alarms = set()

    def worker_pre(self):
        self.log("[ALARM-STREAMER] Initializing threads and preparing inbox.")
        os.makedirs(self.alarm_path, exist_ok=True)
        threading.Thread(target=self.alarm_watcher, daemon=True).start()

    def worker(self):
        interruptible_sleep(self, 20)

    def post_boot(self):
        self.log("[ALARM-STREAMER] Spinning up WebSocket relay...")
        threading.Thread(target=self.launch_socket_server, daemon=True).start()

    def launch_socket_server(self):
        try:
            self.log("[ALARM-STREAMER] Launching secure WebSocket...")
            socketio.run(
                app,
                host='0.0.0.0',
                port=8888,
                certfile='certs/client.crt',
                keyfile='certs/client.key'
            )
        except Exception as e:
            self.log(f"[ALARM-STREAMER][SOCKET-FAIL] {e}")

    def alarm_watcher(self):
        self.log("[ALARM] Swarm alarm watcher online.")
        while True:
            try:
                for fname in os.listdir(self.alarm_path):
                    if not fname.endswith(".alarm"):
                        continue
                    full_path = os.path.join(self.alarm_path, fname)
                    if full_path in self.seen_alarms:
                        continue

                    self.log(f"[ALARM] Detected new alarm file: {fname}")

                    with open(full_path, "r") as f:
                        payload = json.load(f)
                    self.log(f"[ALARM] Emitting: {payload}")
                    socketio.emit("swarm_alarm", payload)
                    self.forward_to_relays(payload)
                    self.seen_alarms.add(full_path)
            except Exception as e:
                self.log(f"[ALARM][ERROR] {e}")
            time.sleep(2)

    def forward_to_relays(self, payload):
        try:
            level = payload.get("level", "default")
            comm_path = self.path_resolution["comm_path"]

            for agent_id in os.listdir(comm_path):
                agent_path = os.path.join(comm_path, agent_id)
                tree_file = os.path.join(agent_path, "agent_tree.json")
                if not os.path.exists(tree_file):
                    continue

                try:
                    with open(tree_file, "r") as f:
                        node = json.load(f)
                except Exception as e:
                    self.log(f"[RELAY][ERROR] Failed to load {tree_file}: {e}")
                    continue

                role = node.get("config", {}).get("role")
                if not role:
                    continue

                inbox_path = os.path.join(comm_path, agent_id, "incoming", role, level)
                os.makedirs(inbox_path, exist_ok=True)

                fname = f"alarm_{int(time.time())}.msg"
                fpath = os.path.join(inbox_path, fname)
                with open(fpath, "w") as f:
                    json.dump(payload, f)

                self.log(f"[RELAY] Sent alarm to {agent_id} → {inbox_path}/{fname}")

        except Exception as e:
            self.log(f"[RELAY-ERROR] Reflex walk failed: {e}")

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = AlarmStreamerAgent(path_resolution, command_line_args)
    agent.boot()