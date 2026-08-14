import ast
import importlib.util
from pathlib import Path
import ssl
import unittest


ROOT = Path(__file__).resolve().parents[1]


def source(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def load_module(relative_path, module_name):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MailTLSSecurityTests(unittest.TestCase):
    helper_paths = (
        "phoenix/matrix_gui/core/utils/mail_tls.py",
        "matrixos/core/python_core/utils/mail_tls.py",
    )

    consumer_paths = (
        "phoenix/matrix_gui/modules/net/connector/egress/smtp/smtp.py",
        "phoenix/matrix_gui/modules/net/connector/ingress/imap/imap.py",
        "matrixos/agents/python_core/matrix_email/matrix_email.py",
        "matrixos/agents/python_core/matrix_email_egress/matrix_email_egress.py",
        "matrixos/agents/python_core/email_send/factory/email_sender_thread.py",
        "matrixos/agents/python_core/email_check/email_check.py",
    )

    def test_mail_context_preserves_identity_verification(self):
        strict_flag = getattr(ssl, "VERIFY_X509_STRICT", 0)
        baseline_flags = ssl.create_default_context().verify_flags

        for index, path in enumerate(self.helper_paths):
            with self.subTest(path=path):
                module = load_module(path, f"mail_tls_policy_{index}")
                context = module.create_mail_tls_context()
                self.assertEqual(ssl.CERT_REQUIRED, context.verify_mode)
                self.assertTrue(context.check_hostname)
                self.assertEqual(
                    baseline_flags & ~strict_flag,
                    context.verify_flags,
                )

    def test_mail_consumers_never_use_implicit_or_unverified_tls(self):
        for path in self.consumer_paths:
            with self.subTest(path=path):
                text = source(path)
                tree = ast.parse(text, filename=path)
                self.assertIn("create_mail_tls_context", text)
                self.assertNotIn("ssl.create_default_context", text)
                self.assertNotIn("ssl.CERT_NONE", text)
                self.assertNotIn("check_hostname = False", text)
                self.assertNotIn("_create_unverified_context", text)

                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    if not isinstance(node.func, ast.Attribute):
                        continue

                    keywords = {keyword.arg for keyword in node.keywords}
                    if node.func.attr == "IMAP4_SSL":
                        self.assertIn("ssl_context", keywords)
                    elif node.func.attr == "SMTP_SSL":
                        self.assertIn("context", keywords)
                    elif node.func.attr == "starttls":
                        self.assertTrue(
                            {"context", "ssl_context"} & keywords,
                            f"TLS context missing at {path}:{node.lineno}",
                        )


if __name__ == "__main__":
    unittest.main()
