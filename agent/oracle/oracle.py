# 🧠 OracleAgent — MatrixSwarm Prototype
# Purpose: Responds to `.prompt` files dropped into its payload folder
# Returns OpenAI-generated responses into `outbox/`

# ======== 🛬 LANDING ZONE BEGIN 🛬 ========"
# ======== 🛬 LANDING ZONE END 🛬 ========"

import os
import json
import time
import threading
from openai import OpenAI
from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    def __init__(self, path_resolution, command_line_args, tree_node):
        super().__init__(path_resolution, command_line_args, tree_node)

        self.api_key = os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key)
        self.prompt_path = os.path.join(self.path_resolution["comm_path_resolved"], "payload")
        self.outbox_path = os.path.join(self.path_resolution["comm_path_resolved"], "outbox")


    def worker_pre(self):
        if not self.api_key:
            self.log("[ORACLE][ERROR] No API key detected. Is your .env loaded?")
        else:
            self.log("[ORACLE] Pre-boot hooks initialized.")
            #threading.Thread(target=self.start_broadcast_listener, daemon=True).start()

    def worker_post(self):
        self.log("[ORACLE] Oracle shutting down. No more prophecies today.")

    def worker(self):
        self.check_prompts_once()
        interruptible_sleep(self, 10)

    def check_prompts_once(self):
        try:
            for filename in os.listdir(self.prompt_path):
                path = os.path.join(self.prompt_path, filename)

                if filename.endswith(".prompt"):
                    with open(path, "r") as f:
                        prompt = f.read().strip()
                    response = self.query_openai(prompt)
                    out_filename = filename.replace(".prompt", ".response")
                    out_path = os.path.join(self.outbox_path, out_filename)
                    with open(out_path, "w") as f:
                        f.write(response)
                    self.log(f"[ORACLE] Responded to {filename}")
                    os.remove(path)

                elif filename.endswith(".json"):
                    with open(path, "r") as f:
                        try:
                            payload = json.load(f)
                        except Exception as e:
                            self.log(f"[ORACLE][ERROR] Failed to parse {filename}: {e}")
                            continue

                    query_type = payload.get("query_type")

                    if query_type == "email_analysis":
                        self.handle_email_analysis(payload)
                        self.log(f"[ORACLE] Email analysis complete: {filename}")
                        os.remove(path)

                    elif query_type == "spawn_suggestion":
                        self.handle_spawn_suggestion(payload)
                        self.log(f"[ORACLE] Spawn suggestion dispatched: {filename}")
                        os.remove(path)

        except Exception as e:
            self.log(f"[ORACLE][ERROR] {e}")

    def on_broadcast_codex_sync(self, packet):
        self.log(f"[ORACLE] ⚡ Received Codex sync broadcast: {packet}")
        # Optional: self.reload_codex(), self.confirm(), etc.

    #called from command_listener() in boot_agent
    def cmd_diagnose(self, command, packet):
        self.log(f"[COMMAND] Received '{command}' with payload: {json.dumps(packet, indent=2)}")

    def on_broadcast_reboot(self, packet):
        self.log(f"[ORACLE] Broadcast requested reboot.")
        self.running = False

    def handle_spawn_suggestion(self, query):
        payload = query.get("spawn", {})
        reason = query.get("reason", "No reason provided.")
        target = query.get("response_to", "matrix")

        universal_id = payload.get("universal_id")
        agent_name = payload.get("agent_name")
        directives = payload.get("directives", {})

        if not universal_id or not agent_name:
            self.log("[ORACLE][SPAWN][ERROR] Missing universal_id or agent_name.")
            return

        spawn_cmd = {
            "command": "spawn_agent",
            "payload": {
                "universal_id": universal_id,
                "agent_name": agent_name,
                "directives": directives
            }
        }

        spawn_dir = os.path.join(self.path_resolution["comm_path"], "matrix", "payload")
        os.makedirs(spawn_dir, exist_ok=True)
        fname = f"oracle_spawn_{int(time.time())}.json"
        with open(os.path.join(spawn_dir, fname), "w") as f:
            json.dump(spawn_cmd, f, indent=2)

        self.log(f"[ORACLE] Dispatched spawn request for {agent_name} to Matrix. Reason: {reason}")

        try:
            mailman = os.path.join(self.path_resolution["comm_path"], "mailman-1", "payload")
            os.makedirs(mailman, exist_ok=True)
            notice = {
                "uuid": "oracle-1",
                "timestamp": time.time(),
                "severity": "info",
                "msg": f"Spawn order issued to Matrix for {agent_name} ({universal_id}) :: {reason}"
            }
            with open(os.path.join(mailman, f"oracle_notice_{int(time.time())}.json"), "w") as f:
                json.dump(notice, f, indent=2)
        except Exception as e:
            self.log(f"[ORACLE][MAILMAN][ERROR] {e}")

    def handle_email_analysis(self, query):
        payload = query.get("payload", {})
        subject = payload.get("subject", "")
        body = payload.get("body", "")
        sender = payload.get("from", "unknown")
        intent = payload.get("intent", "classify")
        action = payload.get("action", "log_only")

        is_spam = any(word in subject.lower() for word in ["win", "crypto", "offer", "$$$", "deal"])
        confidence = 0.9 if is_spam else 0.6
        classification = "spam" if is_spam else "normal"
        action_taken = "interrupted" if is_spam and "interrupt" in action else "logged" if not is_spam else "none"

        response = {
            "source": "oracle-1",
            "response_to": query.get("source", "unknown"),
            "classification": classification,
            "confidence": confidence,
            "action_taken": action_taken,
            "message": f"Subject analyzed. Flagged as {classification}.",
            "timestamp": time.time()
        }
        self.send_oracle_reply(query, response)

    def query_openai(self, prompt):
        try:
            response = self.client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"[ORACLE][ERROR] Failed to query OpenAI: {e}"

    def send_oracle_reply(self, query, response):
        recipient = query.get("response_to")
        if not recipient:
            self.log("[ORACLE][REPLY][ERROR] No response_to field in query.")
            return

        try:
            inbox = os.path.join(self.path_resolution["comm_path"], recipient, "incoming")
            os.makedirs(inbox, exist_ok=True)
            fname = f"oracle_response_{int(time.time())}.json"
            with open(os.path.join(inbox, fname), "w") as f:
                json.dump(response, f, indent=2)
            self.log(f"[ORACLE] Reply sent to {recipient}: {fname}")
        except Exception as e:
            self.log(f"[ORACLE][REPLY-FAIL] Failed to deliver reply: {e}")

if __name__ == "__main__":
    agent = Agent(path_resolution, command_line_args, tree_node)
    agent.boot()
