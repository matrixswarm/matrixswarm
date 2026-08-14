import ast
import importlib.util
from pathlib import Path
import ssl
import sys
import unittest
from unittest.mock import Mock, patch


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

    def _load_email_sender_worker(self):
        matrixos_root = str(ROOT / "matrixos")
        sys.path.insert(0, matrixos_root)
        try:
            return load_module(
                "matrixos/agents/python_core/email_send/factory/"
                "email_sender_thread.py",
                "email_sender_thread_under_test",
            )
        finally:
            sys.path.remove(matrixos_root)

    @staticmethod
    def _worker_payload(encryption):
        return {
            "smtp_server": "smtp.example.test",
            "smtp_port": 465 if encryption == "SSL" else 587,
            "encryption": encryption,
            "from_addr": "sender@example.test",
            "to_addr": "recipient@example.test",
            "password": "test-only-password",
            "subject": "TLS test",
            "body": "test body",
        }

    def test_email_send_factory_exports_managed_worker_contract(self):
        path = (
            "matrixos/agents/python_core/email_send/factory/"
            "email_sender_thread.py"
        )
        tree = ast.parse(source(path), filename=path)
        classes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }

        self.assertIn("EmailSenderThread", classes)
        self.assertNotIn("Agent", classes)

        methods = {
            node.name
            for node in classes["EmailSenderThread"].body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertTrue({"__init__", "run"} <= methods)

    def test_email_sender_worker_passes_verified_context_to_ssl(self):
        module = self._load_email_sender_worker()
        tls_context = object()
        smtp = Mock()
        smtp.__enter__ = Mock(return_value=smtp)
        smtp.__exit__ = Mock(return_value=False)
        shared = {
            "thread_id": "worker-1",
            "context": {
                "payload": self._worker_payload("SSL"),
                "queue_manager": Mock(),
            },
        }

        with (
            patch.object(
                module,
                "create_mail_tls_context",
                return_value=tls_context,
            ),
            patch.object(module.smtplib, "SMTP_SSL", return_value=smtp)
            as smtp_ssl,
        ):
            module.EmailSenderThread(Mock(), shared).run()

        smtp_ssl.assert_called_once_with(
            "smtp.example.test",
            465,
            context=tls_context,
            timeout=10,
        )
        smtp.login.assert_called_once_with(
            "sender@example.test",
            "test-only-password",
        )
        smtp.send_message.assert_called_once()
        shared["context"]["queue_manager"].thread_finished.assert_called_once_with(
            "worker-1"
        )

    def test_email_sender_worker_passes_verified_context_to_starttls(self):
        module = self._load_email_sender_worker()
        tls_context = object()
        smtp = Mock()
        smtp.__enter__ = Mock(return_value=smtp)
        smtp.__exit__ = Mock(return_value=False)
        shared = {
            "thread_id": "worker-2",
            "context": {
                "payload": self._worker_payload("STARTTLS"),
                "queue_manager": Mock(),
            },
        }

        with (
            patch.object(
                module,
                "create_mail_tls_context",
                return_value=tls_context,
            ),
            patch.object(module.smtplib, "SMTP", return_value=smtp)
            as smtp_client,
        ):
            module.EmailSenderThread(Mock(), shared).run()

        smtp_client.assert_called_once_with(
            "smtp.example.test",
            587,
            timeout=10,
        )
        smtp.starttls.assert_called_once_with(context=tls_context)
        smtp.send_message.assert_called_once()

    def test_email_sender_worker_rejects_plaintext_modes(self):
        module = self._load_email_sender_worker()
        shared = {
            "thread_id": "worker-3",
            "context": {
                "payload": self._worker_payload("NONE"),
                "queue_manager": Mock(),
            },
        }
        worker = module.EmailSenderThread(Mock(), shared)

        with self.assertRaisesRegex(
            ValueError,
            "SMTP encryption must be SSL, TLS, or STARTTLS",
        ):
            worker._send(Mock())


if __name__ == "__main__":
    unittest.main()
