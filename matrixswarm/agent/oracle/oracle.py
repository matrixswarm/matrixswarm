# 🧠 OracleAgent — MatrixSwarm Prototype
# Purpose: Responds to `.prompt` files dropped into its payload folder
# Returns OpenAI-generated responses into `outbox/`

import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))

import json
import time
import re
from openai import OpenAI
from matrixswarm.core.boot_agent import BootAgent
from matrixswarm.core.class_lib.packet_delivery.utility.encryption.utility.identity import IdentityObject

class Agent(BootAgent):
    def __init__(self):
        super().__init__()

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
            report_to = packet.get("report_final_packet_to")
            response_mode = (content.get("response_mode") or "terse").lower()
        else:
            prompt_text = content
            history = []
            role = "oracle"
            tracer_session_id = packet.get("tracer_session_id", "unknown")
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

                messages = [{"role": "user", "content": prompt_text}]

                response = self.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=messages,
                    temperature=0,
                ).choices[0].message.content.strip()
            except Exception as e:
                self.log(f"[ERROR] Failed to fetch response: {str(e)}")
                return None


            # 🎯 Final payload construction
            mission_status = 1
            query_id = f"q_{int(time.time())}"
            outbox = os.path.join(self.path_resolution["comm_path"], target_uid, "incoming")
            out_path = os.path.join(outbox, f"oracle_reply_{query_id}.msg")

            self.log(response)

            packet = {
                "type": "gpt_analysis",
                "query_id": query_id,
                "tracer_session_id": tracer_session_id,
                "packet_id": int(time.time()),
                "target_universal_id": "sgt-in-arms",
                "role": "oracle",
                "content": {
                    "response": response,
                    "origin": self.command_line_args.get("universal_id", "oracle"),
                    "role": role,
                    "mission_status": mission_status,
                    "history": history
                }
            }

            self.save_to_trace_session(packet, msg_type="msg")

            os.makedirs(outbox, exist_ok=True)
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
        try:
            blocks = re.findall(r'\{(?:[^{}]|(?R))*\}', text, re.DOTALL)
            for b in blocks:
                json.loads(b)  # only return if it's valid
                return b
        except Exception:
            pass
        return "{}"


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
    agent = Agent()
    agent.boot()
