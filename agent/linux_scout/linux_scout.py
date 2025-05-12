
# ======== 🛬 LANDING ZONE BEGIN 🛬 ========"
# ======== 🛬 LANDING ZONE END 🛬 ========"

import os
import json
import subprocess
import time
from core.boot_agent import BootAgent

class Agent(BootAgent):
    def __init__(self, path_resolution, command_line_args, tree_node):
        super().__init__(path_resolution, command_line_args, tree_node)

        self.inbox = os.path.join(self.path_resolution["comm_path"], self.command_line_args["universal_id"], "incoming")
        os.makedirs(self.inbox, exist_ok=True)
        self.log("[LINUX] Ready for scout missions.")

    def worker(self):
        files = [f for f in os.listdir(self.inbox) if f.endswith(".msg")]
        for fname in files:
            fpath = os.path.join(self.inbox, fname)
            try:
                with open(fpath, "r") as f:
                    payload = json.load(f)

                query_id = payload.get("query_id")
                check = payload.get("check")
                reflex_id = payload.get("reflex_id", "gpt-reflex")

                if not query_id or not check:
                    self.log(f"[LINUX][SKIP] Missing fields in {fname}")
                    os.remove(fpath)
                    continue

                result = self.run_check(check)
                self.reply(query_id, result, reflex_id)
            except Exception as e:
                self.log(f"[LINUX][ERROR] {e}")
            try:
                os.remove(fpath)
            except:
                pass

    def run_check(self, command):
        try:
            output = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, timeout=5)
            return output.decode("utf-8").strip()
        except subprocess.CalledProcessError as e:
            return f"[ERROR] {e.output.decode().strip()}"
        except Exception as e:
            return f"[ERROR] Command failed: {e}"

    def reply(self, query_id, message, reflex_id):
        reply_path = os.path.join(self.path_resolution["comm_path"], reflex_id, "incoming", f"{query_id}.msg")
        os.makedirs(os.path.dirname(reply_path), exist_ok=True)
        reply = {
            "query_id": query_id,
            "response": message,
            "ts": int(time.time())
        }
        with open(reply_path, "w") as f:
            json.dump(reply, f, indent=2)
        self.log(f"[LINUX] Scout report sent to {reflex_id}/{query_id}.msg")

if __name__ == "__main__":
    agent = Agent(path_resolution, command_line_args, tree_node)
    agent.boot()