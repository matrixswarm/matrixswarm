"""Regression checks for critical Harvester events in Agent Logs."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARVESTER_PATH = (
    ROOT
    / "matrixos"
    / "agents"
    / "python_core"
    / "harvester"
    / "harvester.py"
)
LOG_PANEL_PATH = (
    ROOT
    / "phoenix"
    / "matrix_gui"
    / "core"
    / "panel"
    / "log_panel"
    / "log_panel.py"
)


class AgentLogSeverityTests(unittest.TestCase):
    def test_harvester_down_events_are_logged_as_critical(self):
        source = HARVESTER_PATH.read_text(encoding="utf-8")
        self.assertIn(
            'level="INFO" if event == "RECOVERY" else "CRITICAL"',
            source,
        )

    def test_agent_log_panel_renders_critical_before_info(self):
        source = LOG_PANEL_PATH.read_text(encoding="utf-8")
        critical = source.index('if "[CRITICAL]" in line')
        info = source.index('elif "[INFO]" in line')

        self.assertLess(critical, info)
        self.assertIn('QColor("#ff3333")', source[critical:info])
        self.assertIn("QFont.Weight.Bold", source[critical:info])


if __name__ == "__main__":
    unittest.main()
