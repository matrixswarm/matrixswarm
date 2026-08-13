from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def source(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


class PublicReleaseSecurityTests(unittest.TestCase):
    def test_known_dummy_matrix_private_key_is_absent(self):
        dummy_path = (
            ROOT
            / "matrixos/core/python_core/trust_templates/matrix_dummy_priv.py"
        )
        self.assertFalse(dummy_path.exists())
        boot_source = source("matrixos/core/python_core/boot_agent.py")
        self.assertNotIn("DUMMY_MATRIX_PRIV", boot_source)
        self.assertIn('keychain["matrix_priv"] = None', boot_source)

    def test_ghost_vault_accepts_absent_matrix_signing_capability(self):
        vault_source = source(
            "matrixos/core/python_core/mixin/ghost_vault.py"
        )
        self.assertIn('payload_dict["matrix_priv_obj"] = None', vault_source)
        self.assertIn("if matrix_priv:", vault_source)

    def test_live_tree_mutation_requires_matrix_signing_capability(self):
        tree_source = source("matrixos/core/python_core/tree_parser.py")
        self.assertIn(
            "Matrix signing capability is required to insert a live node.",
            tree_source,
        )
        self.assertIn(
            "Matrix signing capability is required for identity assignment.",
            tree_source,
        )

    def test_active_transport_paths_do_not_disable_tls_verification(self):
        transport_paths = (
            "phoenix/matrix_gui/modules/net/connector/egress/https/https.py",
            "phoenix/matrix_gui/modules/net/connector/egress/smtp/smtp.py",
            "phoenix/matrix_gui/modules/net/connector/ingress/wss/wss.py",
            "phoenix/matrix_gui/modules/net/connector/ingress/wss/establish_tls_socket.py",
            "phoenix/matrix_gui/modules/net/connector/wss/wss.py",
            "phoenix/matrix_gui/modules/net/connector/wss/establish_tls_socket.py",
            "phoenix/matrix_gui/modules/net/connection_group.py",
            "phoenix/matrix_gui/modules/net/ws_client.py",
            "phoenix/matrix_gui/modules/net/packet_emitter.py",
            "phoenix/matrix_gui/modules/net/utils/https_with_spki.py",
            "phoenix/matrix_gui/core/utils/cert_trust_manager.py",
            "phoenix/matrix_gui/modules/net/connector/ingress/imap/imap.py",
            "matrixos/agents/python_core/email_send/factory/email_sender_thread.py",
            "matrixos/agents/python_core/matrix_email_egress/matrix_email_egress.py",
        )
        for path in transport_paths:
            with self.subTest(path=path):
                text = source(path)
                self.assertNotIn("ssl.CERT_NONE", text)
                self.assertNotIn("check_hostname = False", text)
                self.assertNotIn("verify=False", text)
                self.assertNotIn("_create_unverified_context", text)

    def test_trust_helpers_do_not_offer_unverified_request_paths(self):
        trust_helpers = (
            "matrixos/core/python_core/utils/swarm_trustkit.py",
            "phoenix/matrix_gui/modules/net/utils/swarm_trustkit.py",
        )
        for path in trust_helpers:
            with self.subTest(path=path):
                text = source(path)
                self.assertNotIn("secure_https_request", text)
                self.assertNotIn("verify=False", text)
                self.assertNotIn("_create_unverified_context", text)

    def test_runtime_ssh_paths_do_not_auto_trust_host_keys(self):
        forbidden = ("AutoAddPolicy", "WarningPolicy")
        for path in (ROOT / "phoenix").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                with self.subTest(path=path, marker=marker):
                    self.assertNotIn(marker, text)

    def test_ssh_connection_requires_pinned_fingerprint(self):
        ssh_source = source(
            "phoenix/matrix_gui/modules/railgun/ssh_support.py"
        )
        self.assertIn("probe_ssh_host_fingerprint", ssh_source)
        self.assertIn("PinnedHostKeyPolicy", ssh_source)
        self.assertIn("hmac.compare_digest", ssh_source)

    def test_ephemeral_launches_have_private_runtime_state(self):
        launcher_source = source(
            "phoenix/matrix_gui/modules/net/class_lib/processes/connection_launcher.py"
        )
        self.assertIn(
            "runtime_shared = shared if persistent else dict(shared)",
            launcher_source,
        )

    def test_phoenix_tls_temp_private_keys_are_contained(self):
        loader_source = source(
            "phoenix/matrix_gui/core/utils/cert_loader.py"
        )
        self.assertIn("tempfile.NamedTemporaryFile(", loader_source)
        self.assertGreaterEqual(loader_source.count("0o600"), 2)
        self.assertIn("os.unlink(path)", loader_source)
        self.assertIn(
            "Failed to remove temporary TLS credential material",
            loader_source,
        )
        self.assertNotIn("tempfile.gettempdir()", loader_source)
        self.assertNotIn("Temp files retained", loader_source)

    def test_smtp_credentials_require_encrypted_transport(self):
        smtp_paths = (
            "matrixos/agents/python_core/email_send/factory/email_sender_thread.py",
            "matrixos/agents/python_core/matrix_email_egress/matrix_email_egress.py",
            "phoenix/matrix_gui/modules/net/connector/ingress/imap/imap.py",
        )
        for path in smtp_paths:
            with self.subTest(path=path):
                text = source(path)
                self.assertIn(
                    'mode not in ("SSL", "TLS", "STARTTLS")',
                    text,
                )
                self.assertIn(
                    "SMTP encryption must be SSL, TLS, or STARTTLS",
                    text,
                )
                self.assertNotIn(
                    'if mode in ("TLS", "STARTTLS")',
                    text,
                )


if __name__ == "__main__":
    unittest.main()
