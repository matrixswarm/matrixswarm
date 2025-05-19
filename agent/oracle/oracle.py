# 🧠 OracleAgent — MatrixSwarm Prototype
# Purpose: Responds to `.prompt` files dropped into its payload folder
# Returns OpenAI-generated responses into `outbox/`

# ======== 🛬 LANDING ZONE BEGIN 🛬 ========"
# ======== 🛬 LANDING ZONE END 🛬 ========"

import os
import json
import time
import re
from openai import OpenAI
from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep

class Agent(BootAgent):
    def __init__(self, path_resolution, command_line_args, tree_node):
        super().__init__(path_resolution, command_line_args, tree_node)

        config = self.tree_node.get("config", {})
        self.api_key = config.get("api_key", os.getenv("OPENAI_API_KEY_2"))
        self.log(self.api_key)
        self.client = OpenAI(api_key=self.api_key)
        self.processed_query_ids = set()
        self.prompt_path = os.path.join(self.path_resolution["comm_path_resolved"], "payload")
        self.outbox_path = os.path.join(self.path_resolution["comm_path_resolved"], "outbox")
        os.makedirs(self.prompt_path, exist_ok=True)
        os.makedirs(self.outbox_path, exist_ok=True)
        self.report_final_packet_to='matrix'
        self.use_dummy_data = False

    def worker_pre(self):
        if not self.api_key:
            self.log("[ORACLE][ERROR] No API key detected. Is your .env loaded?")
        else:
            self.log("[ORACLE] Pre-boot hooks initialized.")
            #threading.Thread(target=self.start_broadcast_listener, daemon=True).start()

    def worker_post(self):
        self.log("[ORACLE] Oracle shutting down. No more prophecies today.")

    def msg_prompt(self, content, packet):

        self.log("[ORACLE] Reflex prompt received.")

        if isinstance(content, dict):
            prompt_text = content.get("prompt", "")
            history = content.get("history", [])
            target_uid = content.get("target_universal_id") or packet.get("target_universal_id")
            role = packet.get("role", "oracle")
            tracer_session_id = packet.get("tracer_session_id")
            mission_id = content.get("mission_id", "unknown")
            report_to = packet.get("report_final_packet_to")
            response_mode = (content.get("response_mode") or "terse").lower()
        else:
            prompt_text = content
            history = []
            role = "oracle"
            tracer_session_id = packet.get("tracer_session_id", "unknown")
            mission_id = packet.get("mission_id", "unknown")
            target_uid = packet.get("target_universal_id", "capital_gpt")
            report_to = packet.get("report_final_packet_to", "capital_gpt")
            response_mode = "terse"


        try:

            if report_to is not None:
                self.report_final_packet_to = report_to

            if not prompt_text:
                self.log("[ORACLE][ERROR] Prompt content is empty.")
                return
            if not target_uid:
                self.log("[ORACLE][ERROR] No target_universal_id. Cannot respond.")
                return
            if target_uid == self.command_line_args.get("universal_id"):
                self.log(f"[ORACLE][WARN] Refusing to reflex to self: {target_uid}")
                return

            try:

                self.log(f"[ORACLE] Response mode: {response_mode}")

                system_prompt = {
                    "terse": "Return ONLY a flat dictionary of shell commands with numeric keys...",
                    "verbose": "Return JSON with each command and a short explanation...",
                    "script": "Return a bash script with echo statements...",
                    "table": "Return a markdown table, then the actions block..."
                }.get(response_mode, "Return ONLY a flat dictionary of shell commands with numeric keys...")

                messages = prompt_text if isinstance(prompt_text, list) else [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_text}
                ]

                #self.log(f"[ORACLE] Final messages to GPT:\n{json.dumps(messages, indent=2)}")

                response = self.client.chat.completions.create(
                    model="gpt-3.5-turbo",  # or gpt-3.5-turbo
                    messages=messages,
                    temperature=0.7
                ).choices[0].message.content.strip()

                mission_status = 1

            except Exception as e:
                response = f"[ORACLE][ERROR] GPT failed: {e}"
                mission_status = -1

            # 📦 Package response as .msg
            outbox = os.path.join(self.path_resolution["comm_path"], target_uid, "incoming")

            query_id = f"q_{int(time.time())}"
            out_path = os.path.join(outbox, f"oracle_reply_{query_id}.msg")

            # Fix weird escape sequences before trying to parse
            try:
                clean = Agent.extract_first_json_block(response)
                response_data = json.loads(clean)
            except Exception as e:
                self.log(f"[ORACLE][ERROR] Failed to parse response: {e}")
                self.log(f"[ORACLE][DEBUG] Raw content was:\n{response}")
                response_data = {"summary": "[PARSE ERROR]", "actions": {}, "exit_code": -1}

            if Agent.contains_dangerous_commands(response_data.get("actions", {})):
                self.log("[ORACLE][FIREWALL] Detected a dangerous command in actions. Blocking response.")
                response_data = {
                    "summary": "[COMMAND BLOCKED: Unsafe reflex]",
                    "actions": {},
                    "exit_code": -1
                }

            packet = {
                "type": "gpt_analysis",
                "query_id": query_id,
                "tracer_session_id": tracer_session_id,  # ✅ Required at top level for trace log
                "packet_id": int(time.time()),  # ✅ Required at top level for trace log
                "target_universal_id": "sgt-in-arms",  # ✅ Who it’s going back to
                "role": "oracle",  # Optional but good for log clarity
                "content": {
                    "response": response_data,  # ← raw GPT string (json.loads() downstream)
                    "origin": self.command_line_args.get("universal_id", "oracle"),
                    "role": role,
                    "mission_id": mission_id,
                    "mission_status": mission_status,  # ← 1, 0, -1 etc.
                    "history": history
                }
            }

            #self.log(f"[TRACE] Oracle saving packet #{packet_id} to session {tracer_session_id}")
            self.save_to_trace_session(packet, msg_type="msg")

            with open(out_path, "w") as f:
                json.dump(packet, f, indent=2)

            self.log(f"[ORACLE] Sent GPT reply to {target_uid} as .msg → {query_id}")

        except Exception as e:
            self.log(f"[ORACLE][CRITICAL] Failed during msg_prompt(): {e}")

    @staticmethod
    def contains_dangerous_commands(actions):
        dangerous = ["apt", "yum", "dnf", "install", "remove", "chown", "chmod", "rm", "mv"]
        for cmd in actions.values():
            if any(danger in cmd.lower() for danger in dangerous):
                return True
        return False

    @staticmethod
    def extract_first_json_block(text):
        match = re.search(r'(\{.*\})', text, re.DOTALL)
        return match.group(1) if match else "{}"

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
