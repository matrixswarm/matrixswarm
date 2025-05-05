from agent.core.boot_agent import BootAgent
import threading
from flask import Flask
from flask_socketio import SocketIO
import os
import json
import time
import ssl

ALARM_PATH = "/comm/mailman/incoming"
SEEN = set()

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

# Alarm scanner thread
def alarm_watcher():
    print("[ALARM] Swarm alarm watcher online.")
    while True:
        try:
            for fname in os.listdir(ALARM_PATH):
                if not fname.endswith(".alarm"):
                    continue
                full_path = os.path.join(ALARM_PATH, fname)
                if full_path in SEEN:
                    continue
                with open(full_path, "r") as f:
                    payload = json.load(f)
                    print(f"[ALARM] Emitting: {payload}")
                    socketio.emit("swarm_alarm", payload)
                    SEEN.add(full_path)
        except Exception as e:
            print(f"[ALARM][ERROR] {e}")
        time.sleep(2)

class AlarmStreamerAgent(BootAgent):

    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)

        #config = tree_node.get("config", {})


    def worker_pre(self):
        self.log("[ALARM-STREAMER] Initializing WebSocket thread...")
        threading.Thread(target=alarm_watcher, daemon=True).start()

    def worker(self):
        try:
            self.log("[ALARM-STREAMER] Starting secure WebSocket server...")
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain('certs/client.crt', 'certs/client.key')
            socketio.run(app, host='0.0.0.0', port=8888, ssl_context=context)
        except Exception as e:
            self.log(f"[ALARM-STREAMER][CRASH] {e}")
            time.sleep(10)  # Prevent instant restart loops



if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = AlarmStreamerAgent(path_resolution, command_line_args)
    agent.boot()
