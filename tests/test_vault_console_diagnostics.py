"""Console failures cannot masquerade as rejected encrypted vault writes."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from matrix_gui.modules.vault.crypto import vault_handler


class BrokenStream:
    encoding = "ascii"

    def write(self, text):
        raise BrokenPipeError("test console closed")

    def flush(self):
        pass


class VaultConsoleTests(unittest.TestCase):
    def test_legacy_console_preserves_save_backup_and_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "test-vault.json")
            raw = io.BytesIO()
            stream = io.TextIOWrapper(raw, encoding="cp1252")
            with contextlib.redirect_stdout(stream):
                for index in (1, 2):
                    data = {"deployments": {}, "synthetic": index}
                    vault_handler.save_vault_singlefile(data, "test-only", path)
                    self.assertEqual(data, vault_handler.load_vault_singlefile("test-only", path))
            stream.flush()
            log = raw.getvalue().decode("cp1252")
            self.assertIn("Saved safely", log)
            self.assertIn("Backup created", log)

    def test_broken_consoles_do_not_invalidate_a_saved_vault(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "test-vault.json")
            with contextlib.redirect_stdout(BrokenStream()), contextlib.redirect_stderr(BrokenStream()):
                vault_handler.save_vault_singlefile({"synthetic": True}, "test-only", path)
            self.assertEqual({"synthetic": True}, vault_handler.load_vault_singlefile("test-only", path))

    def test_real_write_failure_still_raises_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "test-vault.json"
            with contextlib.redirect_stdout(io.StringIO()):
                vault_handler.save_vault_singlefile({"original": True}, "test-only", str(path))
            before = path.read_bytes()
            with contextlib.redirect_stdout(BrokenStream()), contextlib.redirect_stderr(BrokenStream()), \
                 patch.object(vault_handler.os, "replace", side_effect=OSError("synthetic disk failure")):
                with self.assertRaisesRegex(OSError, "synthetic disk failure"):
                    vault_handler.save_vault_singlefile({"original": False}, "test-only", str(path))
            self.assertEqual(before, path.read_bytes())
            self.assertFalse(list(path.parent.glob(".vault_*.json")))

    def test_stdout_failure_falls_back_to_stderr(self):
        stderr = io.StringIO()
        with contextlib.redirect_stdout(BrokenStream()), contextlib.redirect_stderr(stderr):
            vault_handler._diagnostic("Diagnostic still visible")
        self.assertIn("Diagnostic still visible", stderr.getvalue())
