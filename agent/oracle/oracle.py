# 🧠 OracleAgent — MatrixSwarm Prototype
# Purpose: Responds to `.prompt` files dropped into its payload folder
# Returns OpenAI-generated responses into `outbox/`

import os
import sys
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
                    if filename.endswith(".prompt"):
                        prompt_file = os.path.join(self.prompt_path, filename)
                        with open(prompt_file, "r") as f:
                            prompt = f.read().strip()

                        response = self.query_openai(prompt)
                        out_filename = filename.replace(".prompt", ".response")
                        out_path = os.path.join(self.outbox_path, out_filename)

                        with open(out_path, "w") as f:
                            f.write(response)

                        self.log(f"[ORACLE] Responded to {filename}")
                        os.remove(prompt_file)

            except Exception as e:
                self.log(f"[ORACLE][ERROR] {e}")

            time.sleep(10)  # Check interval

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
