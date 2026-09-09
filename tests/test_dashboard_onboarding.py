"""Tests for Phoenix's first-swarm dashboard guidance."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTROL_PANEL = ROOT / "phoenix/matrix_gui/core/phoenix_control_panel.py"
DASHBOARD = (
    ROOT / "phoenix/matrix_gui/core/panel/home/phoenix_static_panel.py"
)
SESSION_WINDOW = ROOT / "phoenix/matrix_gui/core/session_window.py"
HIVE_UI = ROOT / "phoenix/matrix_gui/theme/utils/hive_ui.py"
THEME = ROOT / "phoenix/matrix_gui/theme/hive_theme.qss"


class DashboardOnboardingTests(unittest.TestCase):
    def test_dashboard_and_control_panel_sources_compile(self):
        for path in (CONTROL_PANEL, DASHBOARD, SESSION_WINDOW, HIVE_UI):
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

    def test_dashboard_and_live_session_share_content_gutter(self):
        dashboard = DASHBOARD.read_text(encoding="utf-8")
        session = SESSION_WINDOW.read_text(encoding="utf-8")
        metrics = HIVE_UI.read_text(encoding="utf-8")

        self.assertIn("COCKPIT_CONTENT_GUTTER = 6", metrics)
        self.assertIn("COCKPIT_CONTENT_GUTTER, 0, COCKPIT_CONTENT_GUTTER, 0", dashboard)
        self.assertIn("COCKPIT_CONTENT_GUTTER, 0, COCKPIT_CONTENT_GUTTER, 0", session)

    def test_live_session_stack_has_no_outer_frame(self):
        session = SESSION_WINDOW.read_text(encoding="utf-8")
        theme = THEME.read_text(encoding="utf-8")

        self.assertIn('self.stacked.setObjectName("CockpitStack")', session)
        self.assertIn("QStackedWidget#CockpitStack", theme)
        cockpit_rule = theme.split("QStackedWidget#CockpitStack", 1)[1].split("}", 1)[0]
        self.assertIn("border: none", cockpit_rule)
        self.assertNotIn("#CockpitWrapper", theme)

    def test_panel_edges_and_session_status_share_control_deck_grid(self):
        session = SESSION_WINDOW.read_text(encoding="utf-8")
        theme = THEME.read_text(encoding="utf-8")

        self.assertIn("#HomeTab QGroupBox,", theme)
        self.assertIn("QGroupBox#CockpitTreePanel,", theme)
        self.assertIn("QGroupBox#logs", theme)
        aligned_rule = theme.split("#HomeTab QGroupBox,", 1)[1].split("}", 1)[0]
        self.assertIn("margin-left: 0", aligned_rule)
        self.assertIn("margin-right: 0", aligned_rule)
        self.assertIn('box.setObjectName("CockpitTreePanel")', session)
        self.assertIn("default_layout.setSpacing(COCKPIT_CONTENT_GUTTER)", session)
        lower_inset_rule = theme.split(
            "/* Let the two main panels meet the status rail", 1
        )[1].split("}", 1)[0]
        self.assertIn("margin-bottom: 0", lower_inset_rule)
        self.assertIn('status_bar.setObjectName("SessionStatusBar")', session)
        self.assertIn("COCKPIT_CONTENT_GUTTER, 3, COCKPIT_CONTENT_GUTTER, 3", session)
        self.assertIn('badge_style = "padding: 4px 8px;', session)


if __name__ == "__main__":
    unittest.main()
