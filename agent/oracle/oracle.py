# 🧠 OracleAgent — MatrixSwarm Prototype
# Purpose: Responds to `.prompt` files dropped into its payload folder
# Returns OpenAI-generated responses into `outbox/`

import os
import sys
import json
import time
from openai import OpenAI

if path_resolution['agent_path'] not in sys.path:
    sys.path.append(path_resolution['agent_path'])
if path_resolution['root_path'] not in sys.path:
    sys.path.append(path_resolution['root_path'])

from agent.core.boot_agent import BootAgent

class OracleAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key)
        self.prompt_path = os.path.join(self.path_resolution["comm_path_resolved"], "payload")
        self.outbox_path = os.path.join(self.path_resolution["comm_path_resolved"], "outbox")
        os.makedirs(self.outbox_path, exist_ok=True)

    def post_boot(self):
        if not self.api_key:
            self.log("[ORACLE][ERROR] No API key detected. Is your .env loaded?")
        else:
            self.log("[ORACLE] API key loaded. Ready to receive prompts.")

    def worker(self):
        while self.running:
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

            except Exception as e:
                self.log(f"[ORACLE][ERROR] {e}")

            time.sleep(10)



    def handle_email_analysis(self, query):
        payload = query.get("payload", {})
        subject = payload.get("subject", "")
        body = payload.get("body", "")
        sender = payload.get("from", "unknown")
        intent = payload.get("intent", "classify")
        action = payload.get("action", "log_only")

        # Very simple heuristics (can be upgraded later)
        is_spam = any(word in subject.lower() for word in ["win", "crypto", "offer", "$$$", "deal"])
        confidence = 0.9 if is_spam else 0.6

        classification = "spam" if is_spam else "normal"
        action_taken = "none"

        if is_spam and "interrupt" in action:
            action_taken = "interrupted"
            self.log(f"[ORACLE][SPAM] Flagged + interrupted message from {sender}")
        elif not is_spam and "log" in action:
            self.log(f"[ORACLE][INFO] Logged benign message from {sender}")
            action_taken = "logged"

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

if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    oracle = OracleAgent(path_resolution, command_line_args)
    oracle.boot()
