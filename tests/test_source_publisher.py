"""The root publisher updates exactly one existing trusted source file."""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
spec = importlib.util.spec_from_file_location("matrix_source_publish", ROOT / "matrixos/scripts/matrix_source_publish.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux openat2 required")
class SourcePublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.agent = self.base / "agents/python_core/example"
        self.agent.mkdir(parents=True)
        self.path = self.agent / "example.py"
        self.path.write_bytes(b"VALUE = 1\n")
        self.path.chmod(0o644)
        patcher = patch.object(publisher, "trusted_shared_agent_root", side_effect=lambda *a: os.open(self.agent.parent, os.O_RDONLY | os.O_DIRECTORY))
        patcher.start()
        self.addCleanup(patcher.stop)

    def publish(self, content, name="example", digest=None):
        return publisher.publish_source(name, digest or hashlib.sha256(content).hexdigest(),
                                        io.BytesIO(content), base=str(self.base), _owner_uid=os.geteuid(),
                                        _python_exec=sys.executable)

    def test_atomic_replace_preserves_mode_and_verified_hash(self):
        content = b"VALUE = 2\n"
        result = self.publish(content)
        self.assertEqual(self.path.read_bytes(), content)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o644)
        self.assertEqual(result["sha256"], hashlib.sha256(content).hexdigest())

    def test_rejects_invalid_target_hash_and_syntax_without_writing(self):
        for kwargs in ({"name": "../escape"}, {"digest": "0" * 64}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.publish(b"VALUE = 2\n", **kwargs)
        with self.assertRaises(ValueError):
            self.publish(b"not valid python :\n")
        self.assertEqual(self.path.read_bytes(), b"VALUE = 1\n")

    def test_rejects_linked_source_and_writable_source(self):
        outside = self.base / "outside"
        outside.write_bytes(b"VALUE = 1\n")
        self.path.unlink()
        self.path.symlink_to(outside)
        with self.assertRaises(OSError):
            self.publish(b"VALUE = 2\n")
        self.path.unlink()
        os.link(outside, self.path)
        with self.assertRaises(ValueError):
            self.publish(b"VALUE = 2\n")
        self.path.unlink()
        self.path.write_bytes(b"VALUE = 1\n")
        self.path.chmod(0o666)
        with self.assertRaises(ValueError):
            self.publish(b"VALUE = 2\n")
        self.assertEqual(outside.read_bytes(), b"VALUE = 1\n")

    def test_does_not_create_missing_agent_source(self):
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.publish(b"VALUE = 2\n")
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
