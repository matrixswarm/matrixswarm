import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "phoenix/matrix_gui/core/session_window.py"
THEME = ROOT / "phoenix/matrix_gui/theme/hive_theme.qss"
DASHBOARD = ROOT / "phoenix/matrix_gui/core/panel/home/phoenix_static_panel.py"


class PhoenixCockpitLayoutTests(unittest.TestCase):
    def test_session_stack_is_structural_and_borderless(self):
        session = SESSION.read_text(encoding="utf-8")
        theme = THEME.read_text(encoding="utf-8")

        self.assertIn('self.stacked.setObjectName("SessionPanelStack")', session)
        self.assertIn("default_layout.setContentsMargins(0, 4, 0, 4)", session)
        self.assertIn("QStackedWidget#SessionPanelStack", theme)
        self.assertIn("border: none;", theme.split("QStackedWidget#SessionPanelStack", 1)[1])

    def test_session_badges_share_one_uniformly_spaced_row(self):
        session = SESSION.read_text(encoding="utf-8")

        self.assertIn("badge_layout = QHBoxLayout(badge_row)", session)
        self.assertIn("badge_layout.setContentsMargins(6, 0, 0, 0)", session)
        self.assertIn("badge_layout.setSpacing(6)", session)
        self.assertNotIn("left_gutter =", session)

    def test_dashboard_widgets_are_owned_only_by_their_group_layouts(self):
        dashboard = DASHBOARD.read_text(encoding="utf-8")

        self.assertIn("layout.setContentsMargins(0, 4, 0, 0)", dashboard)
        self.assertIn("layout.setSpacing(0)", dashboard)
        dashboard_lines = {line.strip() for line in dashboard.splitlines()}
        self.assertNotIn("layout.addWidget(self.deployment_tree)", dashboard_lines)
        self.assertNotIn("layout.addWidget(self.feed)", dashboard_lines)
        self.assertIn("deploy_layout.setContentsMargins(6, 4, 6, 4)", dashboard)
        self.assertIn("feed_layout.setContentsMargins(6, 4, 6, 4)", dashboard)


if __name__ == "__main__":
    unittest.main()
