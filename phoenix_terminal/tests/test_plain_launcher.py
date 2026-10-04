"""The GUI launcher is not a second terminal authority."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phoenix_terminal.bridge.launcher import launch
from phoenix_terminal.cli import build_parser, run_bridge


class PlainLauncherTests(unittest.TestCase):
    def test_legacy_and_generic_remote_commands_never_dispatch(self):
        for command in (["bridge", "launch", "deployment"],
                        ["bridge", "restart", "session", "agent"],
                        ["bridge", "call", "deployment.launch", "--params", '{"host": "override.invalid"}']):
            args = build_parser().parse_args(command)
            with self.subTest(command=command), patch("phoenix_terminal.cli.call_bridge") as call:
                with self.assertRaisesRegex(ValueError, "Unavailable"):
                    run_bridge(args)
                call.assert_not_called()

    def test_normal_entrypoint_no_bridge_or_session_monkeypatch_and_state_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "phoenix.py").touch()
            (root / "README.md").touch()
            (root / "matrix_gui").mkdir()
            previous = Path.cwd(), sys.argv, list(sys.path)

            def entrypoint(path, run_name):
                self.assertEqual(str(root / "phoenix.py"), path)
                self.assertEqual("__main__", run_name)
                self.assertEqual(root, Path.cwd())
                self.assertEqual([path], sys.argv)
                raise SystemExit(17)

            with patch("phoenix_terminal.bridge.launcher.runpy.run_path", side_effect=entrypoint), \
                 patch("phoenix_terminal.bridge.server.BridgeServer.start") as start:
                self.assertEqual(17, launch(root, root / "must-not-exist"))
                start.assert_not_called()
            self.assertFalse((root / "must-not-exist").exists())
            self.assertEqual(previous, (Path.cwd(), sys.argv, sys.path))
            source = Path(launch.__code__.co_filename).read_text(encoding="utf-8")
            for name in ("session_shim", "PhoenixBackend", "BridgeServer", "QAction", "run_session ="):
                self.assertNotIn(name, source)

    def test_invalid_root_does_not_execute(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch("phoenix_terminal.bridge.launcher.runpy.run_path") as run:
            with self.assertRaises(ValueError):
                launch(Path(directory), Path(directory))
            run.assert_not_called()
