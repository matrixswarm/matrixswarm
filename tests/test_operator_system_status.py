"""Tests for the no-input, read-only Operator Agent pilot MCP server."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "matrixos"
    / "agents"
    / "python_core"
    / "operator_agent"
    / "mcp_tools"
    / "system_status_server.py"
)
SPEC = importlib.util.spec_from_file_location("operator_system_status", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class OperatorSystemStatusTests(unittest.TestCase):
    def test_snapshot_is_bounded_and_contains_no_control_surface(self):
        snapshot = MODULE.system_status()
        self.assertEqual(
            set(snapshot),
            {"observed_at", "uptime_sec", "load_average", "memory", "root_filesystem"},
        )
        self.assertIsInstance(snapshot["observed_at"], int)
        self.assertTrue(snapshot["uptime_sec"] is None or snapshot["uptime_sec"] >= 0)
        if snapshot["load_average"] is not None:
            self.assertEqual(len(snapshot["load_average"]), 3)
        for field in ("memory", "root_filesystem"):
            value = snapshot[field]
            if value is not None:
                self.assertEqual(
                    set(value), {"total_bytes", "available_bytes", "used_bytes"}
                )
                self.assertGreaterEqual(value["total_bytes"], value["available_bytes"])

    def test_server_has_one_fixed_no_argument_tool(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("def read_status()", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("sys.argv", source)
        self.assertNotIn("os.environ", source)


if __name__ == "__main__":
    unittest.main()
