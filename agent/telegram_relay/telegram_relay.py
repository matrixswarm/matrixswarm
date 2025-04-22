# 📡 TelegramRelayAgent — Forwards Swarm Logs to Telegram
# Author: ChatGPT, under General Daniel F. MacDonald
import os
import json
import time
import requests
import sys

if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])
from agent.core.boot_agent import BootAgent

class TelegramRelayAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)


        config = tree_node.get("config", {}) if 'tree_node' in globals() else {}

        self.token = config.get("bot_token")
        self.chat_id = config.get("chat_id")
        self.comm_folder = config.get("watch_comm", "mailman-1")

        os.makedirs(self.path_resolution["comm_path_resolved"], exist_ok=True)

    def post_boot(self):
        self.log("[TELEGRAM] TelegramRelayAgent online. Watching for messages.")

    def worker(self):
        while self.running:
            try:
                path=os.path.join(self.path_resolution["comm_path_resolved"],'incoming')
                for file in os.listdir(path):
                    if file.endswith(".msg"):
                        path = os.path.join(path, file)
                        with open(path, "r") as f:
                            try:
                                content = f.read()
                                if not content.strip():
                                    raise ValueError("File is empty")
                                data = json.loads(content)
                            except Exception as e:
                                self.log(f"[TELEGRAM][ERROR] Failed to parse {file}: {e}")
                                os.remove(path)
                                continue

                        message = self.format_message(data)
                        self.send_to_telegram(message)
                        os.remove(path)
            except Exception as e:
                self.log(f"[TELEGRAM][ERROR] {e}")
            time.sleep(5)

    def format_message(self, data):
        lines = [f"📣 Swarm Message"]
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
            self.log("[TELEGRAM] Message sent to Telegram.")
        except Exception as e:
            self.log(f"[TELEGRAM][ERROR] Telegram delivery failed: {e}")

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = TelegramRelayAgent(path_resolution, command_line_args)
    agent.boot()