import os
import json
import time
import socket
import ssl
import threading
from datetime import datetime
import importlib.util
import sys
import uuid

# === Load womb.py dynamically ===
womb_path = os.path.join(os.path.dirname(__file__), "womb.py")
spec = importlib.util.spec_from_file_location("womb", womb_path)
womb = importlib.util.module_from_spec(spec)
sys.modules["womb"] = womb
spec.loader.exec_module(womb)

AgentWomb = womb.AgentWomb

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../core"))


MESSAGE_QUEUE_PATH = "/sites/orbit/python/message_queue.json"
TLS_PORT = 65431
HEALTH_CHECK_INTERVAL = 15

class MatrixAgent(AgentWomb):
    def __init__(self, agent_name, version, revision, uuid_str):
        super().__init__(agent_name, version, revision, uuid_str)
        self.agent_state = {}
        self.running = True
        self.start_time = time.time()

        self.log("MatrixAgent booting...")

        threading.Thread(target=self.tail_queue, daemon=True).start()
        threading.Thread(target=self.listen_tls, daemon=True).start()
        threading.Thread(target=self.health_check_loop, daemon=True).start()

    def tail_queue(self):
        if not os.path.exists(MESSAGE_QUEUE_PATH):
            self.log("Message queue path does not exist.")
            return
        with open(MESSAGE_QUEUE_PATH, "r") as f:
            f.seek(0, os.SEEK_END)
            while not self.shutdown_flag.is_set():
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                try:
                    msg = json.loads(line.strip())
                    self.process_message(msg)
                except Exception as e:
                    self.log(f"Failed to process tail line: {e}")

    def listen_tls(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile="certs/server.crt", keyfile="certs/server.key")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("0.0.0.0", TLS_PORT))
            server.listen(5)
            self.log(f"Listening on TLS port {TLS_PORT}")
            while not self.shutdown_flag.is_set():
                try:
                    conn, _ = server.accept()
                    secure_conn = context.wrap_socket(conn, server_side=True)
                    threading.Thread(target=self.handle_tls_client, args=(secure_conn,), daemon=True).start()
                except Exception as e:
                    self.log(f"TLS accept error: {e}")

    def handle_tls_client(self, conn):
        with conn:
            for line in conn.makefile():
                try:
                    msg = json.loads(line.strip())
                    self.process_message(msg)
                except Exception as e:
                    self.log(f"TLS message error: {e}")

    def process_message(self, msg):
        msg_type = msg.get("type")

        if msg_type == "matrix_request":
            message = msg.get("source_value", {}).get("message", "").lower()
            if message == "status":
                self.report_status()
            elif message == "agent_list":
                self.report_agent_list()
            elif message.startswith("restart"):
                self.forward("mediator_restart_request", message)
            elif message.startswith("kill"):
                self.forward("mediator_kill_request", message)
            elif message.startswith("freeze"):
                self.forward("mediator_freeze_request", message)
            elif message.startswith("priority"):
                self.forward("mediator_priority_update", message)
            else:
                self.log(f"Unknown matrix request: {message}")
        elif msg_type == "agent_status":
            agent_id = msg.get("agent_id")
            self.agent_state[agent_id] = {
                "status": msg.get("status"),
                "last_seen": msg.get("last_seen"),
                "name": msg.get("name"),
                "version": msg.get("version"),
                "revision": msg.get("revision")
            }
        else:
            self.log(f"Unknown message type: {msg_type}")

    def forward(self, new_type, message):
        parts = message.strip().split()
        if len(parts) < 2:
            self.log(f"Invalid command format: {message}")
            return
        target_uuid = parts[1]
        payload = {
            "type": new_type,
            "agent_uuid": target_uuid,
            "source": self.agent_name,
            "timestamp": datetime.utcnow().isoformat()
        }
        if new_type == "mediator_priority_update" and len(parts) == 3:
            payload["priority"] = parts[2]
        self.log(f"Forwarding {new_type} to mediator for {target_uuid}")
        self.send_message(payload)

    def report_status(self):
        payload = {
            "type": "matrix_status",
            "agent": self.agent_name,
            "version": self.version,
            "revision": self.revision,
            "uptime": f"{round(time.time() - self.start_time, 2)}s",
            "timestamp": datetime.utcnow().isoformat()
        }
        self.send_message(payload)

    def report_agent_list(self):
        report = {
            "type": "matrix_agent_list",
            "agents": list(self.agent_state.keys()),
            "timestamp": datetime.utcnow().isoformat()
        }
        self.send_message(report)

    def health_check_loop(self):
        while not self.shutdown_flag.is_set():
            time.sleep(HEALTH_CHECK_INTERVAL)
            report = {
                "type": "matrix_health_report",
                "agent_count": len(self.agent_state),
                "timestamp": datetime.utcnow().isoformat()
            }
            self.send_message(report)

# === Entrypoint ===
if __name__ == "__main__":
    AGENT_NAME = "matrix_agent"
    VERSION = "1"
    REVISION = "2"
    UUID = str(uuid.uuid5(uuid.NAMESPACE_DNS, AGENT_NAME + VERSION + REVISION))

    MatrixAgent(AGENT_NAME, VERSION, REVISION, UUID)
    while True:
        time.sleep(10)
