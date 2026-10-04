"""Synthetic encrypted Vault snapshot tests; no production credentials."""

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from phoenix_terminal.cli import build_parser
from phoenix_terminal.terminal_runtime import build_snapshot, run_terminal
from phoenix_terminal.connection_approval import ApprovalResource
from phoenix_terminal.connection_broker import TerminalSnapshot


REPO = Path(__file__).resolve().parents[2]
PHOENIX = REPO / "phoenix"
sys.path.insert(0, str(PHOENIX))
from matrix_gui.modules.vault.crypto.vault_handler import save_vault_singlefile


def vault(enabled=True):
    return {
        "deployments": {
            "deployment-a": {"label": "Alpha", "agents": []},
            "deployment-b": {"label": "Beta", "agents": []},
        },
        "registry": {"secret": "SYNTHETIC-HIDDEN"},
        "workspaces": {},
        "terminal_access": {
            "schema_version": 1,
            "enabled": enabled,
            "approval_lifetime_seconds": 300,
            "permissions": {
                "alerts.read": {
                    "enabled": True,
                    "deployment_ids": ["deployment-a"],
                }
            },
        },
    }


class SnapshotTests(unittest.TestCase):
    def _save(self, directory, data):
        path = Path(directory) / "synthetic.json"
        with contextlib.redirect_stdout(io.StringIO()):
            save_vault_singlefile(data, "synthetic-only", str(path))
        return path

    def test_snapshot_contains_all_resources_but_no_secrets_or_operations(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self._save(temporary, vault())
            before = path.read_bytes()
            result = build_snapshot(PHOENIX, path, "synthetic-only")
            self.assertEqual(300, result.approval_lifetime_seconds)
            self.assertEqual(
                ["deployment-a", "deployment-b"],
                [item.deployment_id for item in result.resources],
            )
            self.assertTrue(all(item.operations == () for item in result.resources))
            self.assertNotIn("SYNTHETIC-HIDDEN", repr(result))
            self.assertEqual(before, path.read_bytes())

    def test_supported_alert_adapter_gets_only_the_saved_deployment_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self._save(temporary, vault())
            result = build_snapshot(
                PHOENIX,
                path,
                "synthetic-only",
                supported_operations=("alerts.read",),
            )
            operations = {
                item.deployment_id: item.operations for item in result.resources
            }
            self.assertEqual(("alerts.read",), operations["deployment-a"])
            self.assertEqual((), operations["deployment-b"])

    def test_runtime_cannot_declare_an_unknown_adapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self._save(temporary, vault())
            with self.assertRaisesRegex(ValueError, "unsupported operation"):
                build_snapshot(
                    PHOENIX,
                    path,
                    "synthetic-only",
                    supported_operations=("shell.exec",),
                )

    def test_disabled_policy_and_foreign_scope_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            disabled = self._save(temporary, vault(enabled=False))
            with self.assertRaisesRegex(ValueError, "disabled"):
                build_snapshot(PHOENIX, disabled, "synthetic-only")
        with tempfile.TemporaryDirectory() as temporary:
            data = vault()
            data["terminal_access"]["permissions"]["alerts.read"]["deployment_ids"] = ["foreign"]
            invalid = self._save(temporary, data)
            with self.assertRaisesRegex(ValueError, "outside this Vault"):
                build_snapshot(PHOENIX, invalid, "synthetic-only")

    def test_cli_exposes_no_password_or_approve_switch(self):
        parser = build_parser()
        base = [
            "terminal",
            "open",
            "--phoenix-root",
            str(PHOENIX),
            "--vault",
            "synthetic.json",
        ]
        parsed = parser.parse_args(base)
        self.assertEqual("open", parsed.terminal_command)
        for option in ("--password", "--approve", "--yes", "--allow-all"):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(base + [option, "bad"])


class RuntimeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_exit_start_failure_and_event_loop_failure_revoke_and_close(self):
        from PyQt6.QtWidgets import QApplication
        view = TerminalSnapshot("Synthetic", "c" * 64,
            (ApprovalResource("allowed", "Fixture", ("alerts.read",)),), 60)
        for failure in (None, "start", "event-loop"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                feed = Mock()
                server = Mock()
                observed = {}
                def start_feeds(supplier):
                    observed["grants"] = supplier
                    self.assertEqual({}, supplier())  # No request/approval on launch.
                feed.start.side_effect = start_feeds
                if failure == "start":
                    server.start.side_effect = RuntimeError("Synthetic startup failure")
                def exec_app():
                    if failure == "event-loop":
                        raise RuntimeError("Synthetic event loop failure")
                    return 0
                with contextlib.ExitStack() as stack:
                    stack.enter_context(patch("phoenix_terminal.terminal_runtime._require_desktop"))
                    stack.enter_context(patch("phoenix_terminal.terminal_runtime._require_private_password_prompt", return_value="fixture-only"))
                    stack.enter_context(patch("phoenix_terminal.terminal_runtime.load_live_toolkit", return_value=(view, {})))
                    stack.enter_context(patch("phoenix_terminal.live_alerts.LiveAlertFeeds", return_value=feed))
                    server_factory = stack.enter_context(patch("phoenix_terminal.terminal_runtime.TerminalRequestServer", return_value=server))
                    stack.enter_context(patch.object(QApplication, "exec", side_effect=exec_app))
                    stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                    if failure:
                        with self.assertRaisesRegex(RuntimeError, "Synthetic"):
                            run_terminal(PHOENIX, "unused-fixture.json", temporary)
                    else:
                        self.assertEqual(0, run_terminal(PHOENIX, "unused-fixture.json", temporary))
                    feed.close.assert_called_once()
                    server.stop.assert_called_once()
                    handler = server_factory.call_args.args[0]
                    with self.assertRaisesRegex(PermissionError, "locked"):
                        handler("terminal.status", {})
                    if failure == "start":
                        feed.start.assert_not_called()
                    else:
                        self.assertEqual({}, observed["grants"]())


if __name__ == "__main__":
    unittest.main()
