"""Managed SMTP worker used by the email_send queue."""

import smtplib
from email.message import EmailMessage

from core.python_core.utils.mail_tls import create_mail_tls_context


class EmailSenderThread:
    """Send one queued email through a verified TLS transport."""

    _TLS_MODES = frozenset({"SSL", "TLS", "STARTTLS"})

    def __init__(self, log, shared):
        self.log = log
        self.shared = shared
        self.payload = shared["context"]["payload"]

    def run(self):
        try:
            message = EmailMessage()
            message["From"] = self.payload["from_addr"]
            message["To"] = self.payload["to_addr"]
            message["Subject"] = self.payload["subject"]
            message.set_content(self.payload["body"])
            self._send(message)
        except Exception as error:
            self.log("[EMAIL][ERROR] Send failure", error=error)
        finally:
            self._notify_queue_manager()

    def _send(self, message):
        mode = str(self.payload.get("encryption") or "").strip().upper()
        if mode not in self._TLS_MODES:
            raise ValueError(
                "SMTP encryption must be SSL, TLS, or STARTTLS"
            )

        host = self.payload["smtp_server"]
        port = self.payload["smtp_port"]
        username = self.payload["from_addr"]
        password = self.payload["password"]
        context = create_mail_tls_context()

        if mode == "SSL":
            self.log(f"[EMAIL][CONNECT] Using SSL on {host}:{port}")
            with smtplib.SMTP_SSL(
                host,
                port,
                context=context,
                timeout=10,
            ) as server:
                server.login(username, password)
                server.send_message(message)
            self.log("[EMAIL][SEND] Sent via SSL.")
            return

        self.log(f"[EMAIL][CONNECT] Using STARTTLS on {host}:{port}")
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(username, password)
            server.send_message(message)
        self.log("[EMAIL][SEND] Sent via STARTTLS.")

    def _notify_queue_manager(self):
        context = self.shared.get("context", {})
        worker_id = self.shared.get("thread_id") or context.get("thread_id")
        manager = context.get("queue_manager")
        if worker_id and manager:
            manager.thread_finished(worker_id)
