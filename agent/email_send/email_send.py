import sys
import os
sys.path.insert(0, os.getenv("SITE_ROOT"))
sys.path.insert(0, os.getenv("AGENT_PATH"))
import json
from dotenv import load_dotenv
from core.boot_agent import BootAgent
from core.utils.swarm_sleep import interruptible_sleep
load_dotenv()

class Agent(BootAgent):
    def __init__(self):
        super().__init__()

        self.watch_path = os.path.join(self.path_resolution["comm_path_resolved"], "payload")
        os.makedirs(self.watch_path, exist_ok=True)

        config = self.tree_node.get("config", {})
        self.smtp_host = config.get("smtp_host") or os.getenv("EMAILSENDAGENT_SMTP_HOST")
        self.smtp_port = config.get("smtp_port") or os.getenv("EMAILSENDAGENT_SMTP_PORT")
        self.email_addr = config.get("email") or os.getenv("EMAILSENDAGENT_SMTP_EMAIL")
        self.email_pass = config.get("password") or os.getenv("EMAILSENDAGENT_PASSWORD")

    def worker(self, config:dict = None):

        for fname in os.listdir(self.watch_path):
            if not fname.endswith(".json"):
                continue

            try:
                fpath = os.path.join(self.watch_path, fname)
                with open(fpath, "r") as f:
                    msg_data = json.load(f)

                self.send_email(msg_data)
                self.log(f"[EMAIL] Sent: {msg_data.get('subject')}")
                os.remove(fpath)

            except Exception as e:
                self.log(f"[EMAIL][ERROR] Failed to send {fname}: {e}")
        interruptible_sleep(self, 4)

    def send_email(self, data):
        from email.message import EmailMessage
        import smtplib

        msg = EmailMessage()
        msg["From"] = self.email_addr
        msg["To"] = data["to"]
        msg["Subject"] = data["subject"]
        msg.set_content(data["body"])

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(self.email_addr, self.email_pass)
                try:
                    server.send_message(msg)
                    self.log(f"[EMAIL] Sent: {data['subject']}")
                except smtplib.SMTPResponseException as e:
                    self.log(f"[EMAIL][SMTP-FAIL] Code: {e.smtp_code}, Msg: {e.smtp_error}")
                except Exception as e:
                    self.log(f"[EMAIL][ERROR] Failed to send: {e}")

        except Exception as e:
            self.log(f"[EMAIL][ERROR] Failed to send: {e}")


if __name__ == "__main__":
    agent = Agent()
    agent.boot()