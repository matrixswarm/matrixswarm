from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[1]
SMTP_CONNECTOR = (
    ROOT
    / "phoenix"
    / "matrix_gui"
    / "modules"
    / "net"
    / "connector"
    / "egress"
    / "smtp"
    / "smtp.py"
)


class PhoenixSMTPConnectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SMTP_CONNECTOR.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_honors_implicit_tls_and_starttls_modes(self):
        self.assertIn("smtplib.SMTP_SSL(", self.source)
        self.assertIn("server.starttls(context=context)", self.source)
        self.assertIn('conn.get("smtp_encryption")', self.source)

    def test_rejects_cleartext_smtp_configuration(self):
        self.assertIn(
            'mode not in {"SSL", "TLS", "STARTTLS"}',
            self.source,
        )

    def test_reports_send_failure_instead_of_false_success(self):
        self.assertIn("if self.send(packet):", self.source)
        self.assertIn("payload was not accepted by SMTP", self.source)
        self.assertIn('self._emit_status("error")', self.source)


if __name__ == "__main__":
    unittest.main()
