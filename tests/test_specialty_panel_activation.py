from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SESSION_WINDOW = ROOT / "phoenix/matrix_gui/core/session_window.py"
EMAIL_SEND = (
    ROOT
    / "phoenix/matrix_gui/core/panel/custom_panels/email_send/email_send.py"
)


def source(path):
    return path.read_text(encoding="utf-8")


class SpecialtyPanelActivationTests(unittest.TestCase):
    def test_sources_compile(self):
        for path in (SESSION_WINDOW, EMAIL_SEND):
            with self.subTest(path=path):
                compile(source(path), str(path), "exec")

    def test_specialty_panels_schedule_activation_after_stack_switch(self):
        text = source(SESSION_WINDOW)
        self.assertGreaterEqual(
            text.count("self._schedule_specialty_panel_activation(panel)"),
            2,
        )
        self.assertLess(
            text.index("self.stacked.setCurrentWidget(panel)"),
            text.index(
                "self._schedule_specialty_panel_activation(panel)",
                text.index("self.stacked.setCurrentWidget(panel)"),
            ),
        )
        self.assertIn("QTimer.singleShot(", text)
        self.assertIn("self.activateWindow()", text)
        self.assertIn(
            'activation_hook = getattr(panel, "on_panel_activated", None)',
            text,
        )

    def test_email_panel_focuses_and_repaints_editors(self):
        text = source(EMAIL_SEND)
        self.assertIn("def on_panel_activated(self):", text)
        self.assertIn(
            "self.subject.setFocus(Qt.FocusReason.OtherFocusReason)",
            text,
        )
        self.assertIn("self.subject.update()", text)
        self.assertIn("self.body.viewport().update()", text)

    def test_recipient_history_uses_line_edit_completion(self):
        text = source(EMAIL_SEND)
        self.assertIn("QCompleter(recipients, self.to_address)", text)
        self.assertIn("self.to_address.setCompleter", text)
        self.assertNotIn("self.to_address.addItem", text)
        self.assertNotIn("self.to_address.currentText", text)


if __name__ == "__main__":
    unittest.main()
