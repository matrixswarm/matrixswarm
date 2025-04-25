import os
import time
import json
import imaplib
import email
import socket

socket.setdefaulttimeout(10)  # Set a 10-second global timeout for sockets

from email.header import decode_header
from dotenv import load_dotenv
load_dotenv()
from agent.core.boot_agent import BootAgent
from agent.core.utils.swarm_sleep import interruptible_sleep


class EmailCheckAgent(BootAgent):
    def __init__(self, path_resolution, command_line_args):
        super().__init__(path_resolution, command_line_args)

        config = tree_node.get("config", {})

        self.interval = config.get("interval", int(os.getenv("EMAILCHECKAGENT_INTERVAL", 60)))
        self.mail_host = config.get("imap_host") or os.getenv("EMAILCHECKAGENT_IMAP_HOST")
        self.mail_user = config.get("email") or os.getenv("EMAILCHECKAGENT_EMAIL")
        self.mail_pass = config.get("password") or os.getenv("EMAILCHECKAGENT_PASSWORD")
        self.report_to = config.get("report_to") or os.getenv("EMAILCHECKAGENT_REPORT_TO", "mailman-1")
        self.payload_dir = os.path.join(self.path_resolution["comm_path"], self.report_to, "payload")
        os.makedirs(self.payload_dir, exist_ok=True)

    def worker(self):
        socket.setdefaulttimeout(10)
        while self.running:
            try:
                with imaplib.IMAP4_SSL(self.mail_host) as mail:
                    mail.login(self.mail_user, self.mail_pass)
                    mail.select("inbox")

                    result, data = mail.search(None, 'UNSEEN')
                    ids = data[0].split()
                    for num in ids:
                        if not self.running:
                            break

                        result, msg_data = mail.fetch(num, "(RFC822)")
                        raw = msg_data[0][1]
                        msg = email.message_from_bytes(raw)

                        subject, encoding = decode_header(msg["Subject"])[0]
                        subject = subject.decode(encoding or "utf-8") if isinstance(subject, bytes) else subject

                        from_email = msg.get("From")
                        payload = {
                            "uuid": self.command_line_args["permanent_id"],
                            "timestamp": time.time(),
                            "from": from_email,
                            "subject": subject,
                            "body": self.extract_body(msg)
                        }

                        fname = f"email_{int(time.time())}.json"
                        with open(os.path.join(self.payload_dir, fname), "w") as f:
                            json.dump(payload, f, indent=2)

                        self.log(f"[EMAIL] Logged message from {from_email}: {subject}")

            except Exception as e:
                self.log(f"[EMAIL][ERROR] {e}")
            interruptible_sleep(self, self.interval)

    def extract_body(self, msg):
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    return part.get_payload(decode=True).decode()
        else:
            return msg.get_payload(decode=True).decode()
        return "[no text]"


if __name__ == "__main__":
    path_resolution["pod_path_resolved"] = os.path.dirname(os.path.abspath(__file__))
    agent = EmailCheckAgent(path_resolution, command_line_args)
    agent.boot()
