# 📡 TelegramRelayAgent — Forwards Swarm Logs to Telegram
# Author: ChatGPT, under General Daniel F. MacDonald

# ======== 🛬 LANDING ZONE BEGIN 🛬 ========"
# ======== 🛬 LANDING ZONE END 🛬 ========"

import os
import json
import requests
from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    def __init__(self, path_resolution, command_line_args, tree_node):
        super().__init__(path_resolution, command_line_args, tree_node)

        config = self.tree_node.get("config", {})

        self.token = config.get("bot_token")
        self.chat_id = config.get("chat_id")
        self.comm_folder = config.get("watch_comm", "mailman-1")

        self.watch_path = os.path.join(self.path_resolution["comm_path_resolved"], "incoming")
        os.makedirs(self.watch_path, exist_ok=True)

    def worker_pre(self):
        self.log("[TELEGRAM] Telegram relay activated. Awaiting message drops...")

    def worker(self):
        interruptible_sleep(self, 230)

    def worker_post(self):
        self.log("[TELEGRAM] Relay shutting down. No more echoes for now.")

    def check_incoming_once(self):
        try:
            for file in os.listdir(self.watch_path):
                if not file.endswith(".msg"):
                    continue
                full_path = os.path.join(self.watch_path, file)
                try:
                    with open(full_path, "r") as f:
                        content = f.read()
                        if not content.strip():
                            raise ValueError("File is empty")
                        data = json.loads(content)
                except Exception as e:
                    self.log(f"[TELEGRAM][ERROR] Failed to parse {file}: {e}")
                    os.remove(full_path)
                    continue

                message = self.format_message(data)
                self.send_to_telegram(message)
                os.remove(full_path)
        except Exception as e:
            self.log(f"[TELEGRAM][ERROR] {e}")

    def format_message(self, data):
        lines = ["📣 Swarm Message"]
        for key, value in data.items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def send_to_telegram(self, message):
        if not self.token or not self.chat_id:
            self.log("[TELEGRAM][ERROR] Missing bot_token or chat_id.")
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            requests.post(url, json={"chat_id": self.chat_id, "text": message})
            self.log("[TELEGRAM] Message relayed.")
        except Exception as e:
            self.log(f"[TELEGRAM][ERROR] Telegram delivery failed: {e}")

def on_alarm(self, payload):
    msg = f"🚨 [{payload['level'].upper()}] {payload['universal_id']} — {payload['cause']}"
    self.send_message_to_platform(msg)

if __name__ == "__main__":
    agent = Agent(path_resolution, command_line_args, tree_node)
    agent.boot()
