from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from phoenix_terminal.monitor import add_target, load_config, redact_url
from phoenix_terminal.cli import safe_console_text


class MonitorTests(unittest.TestCase):
    def test_redact_url_strips_credentials_and_query(self) -> None:
        self.assertEqual(
            redact_url("https://operator:secret@example.com:8443/health?token=hide"),
            "https://example.com:8443/health",
        )

    def test_add_target_writes_local_config(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            add_target(Path(temporary_directory), "site", "https://example.com/health", 204)
            self.assertEqual(
                load_config(Path(temporary_directory))["targets"],
                [{"name": "site", "url": "https://example.com/health", "expected_status": 204}],
            )

    def test_console_text_supports_agent_emoji(self) -> None:
        self.assertIsInstance(safe_console_text("🛡️ uptime_sentinel"), str)
