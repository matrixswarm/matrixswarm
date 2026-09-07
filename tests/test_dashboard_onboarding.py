"""Tests for Phoenix's first-swarm dashboard guidance."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTROL_PANEL = ROOT / "phoenix/matrix_gui/core/phoenix_control_panel.py"
DASHBOARD = (
    ROOT / "phoenix/matrix_gui/core/panel/home/phoenix_static_panel.py"
)


class DashboardOnboardingTests(unittest.TestCase):
    def test_dashboard_and_control_panel_sources_compile(self):
        for path in (CONTROL_PANEL, DASHBOARD):
            with self.subTest(path=path):
                compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_deploy_control_uses_clear_launch_icon_and_help(self):
        source = CONTROL_PANEL.read_text(encoding="utf-8")
        self.assertIn('QPushButton("🚀 Deploy")', source)
        self.assertNotIn('QPushButton("🗘 Deploy")', source)
        self.assertIn('setAccessibleName("Deploy a swarm")', source)
        self.assertIn('QPushButton("🔐 Vault")', source)
        self.assertIn('setAccessibleName("Manage encrypted vault")', source)

    def test_first_swarm_guide_matches_railgun_only_workflow(self):
        source = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn('QGroupBox("🚀 Deploy Your First Swarm")', source)
        for step in (
            "1 · Registry",
            "2 · Deploy",
            "3 · Workspace Deploy",
            "4 · Connect",
        ):
            with self.subTest(step=step):
                self.assertIn(step, source)
        self.assertIn("sealed directive directly into MatrixD memory", source)
        self.assertIn('QGroupBox("🚀 Deployments")', source)


if __name__ == "__main__":
    unittest.main()
