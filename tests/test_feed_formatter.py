"""Tests for Phoenix Swarm Feed severity presentation."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FORMATTER_PATH = (
    ROOT
    / "phoenix"
    / "matrix_gui"
    / "core"
    / "class_lib"
    / "feed"
    / "feed_formatter.py"
)

SPEC = importlib.util.spec_from_file_location("feed_formatter", FORMATTER_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FeedFormatterTests(unittest.TestCase):
    def test_critical_events_render_bright_red(self):
        rendered = MODULE.FeedFormatter.format(
            {
                "timestamp": "2026-09-07 16:54:59",
                "level": "critical",
                "event_type": "alert",
            }
        )

        self.assertIn("style='color:#ff3333;'", rendered)
        self.assertIn("[CRITICAL] [ALERT]", rendered)


if __name__ == "__main__":
    unittest.main()
