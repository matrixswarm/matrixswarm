from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_DIR = ROOT / "phoenix" / "matrix_gui" / "registry"
MANAGER = REGISTRY_DIR / "registry_manager.py"
CONTROL_BAR = ROOT / "phoenix" / "matrix_gui" / "core" / "phoenix_control_panel.py"


class RegistryManagerConsolidationTests(unittest.TestCase):
    def test_only_one_registry_manager_implementation_remains(self):
        self.assertTrue(MANAGER.is_file())
        self.assertFalse((REGISTRY_DIR / "registry_manager_v2.py").exists())
        self.assertNotIn(
            "RegistryManagerDialogV2",
            MANAGER.read_text(encoding="utf-8"),
        )

    def test_control_bar_uses_canonical_registry_manager(self):
        source = CONTROL_BAR.read_text(encoding="utf-8")
        self.assertIn(
            "from matrix_gui.registry.registry_manager import RegistryManagerDialog",
            source,
        )
        self.assertNotIn("registry_manager_v2", source)
        self.assertIn("RegistryManagerDialog(parent=self)", source)

    def test_class_lock_controls_category_visibility(self):
        source = MANAGER.read_text(encoding="utf-8")
        self.assertIn(
            "self.category_row.setVisible(not bool(self.class_lock))",
            source,
        )
        self.assertIn("if self.assign_callback:", source)

    def test_double_click_always_edits(self):
        source = MANAGER.read_text(encoding="utf-8")
        self.assertIn(
            "list_widget.itemDoubleClicked.connect(self._edit_via_double_click)",
            source,
        )
        self.assertIn("self._edit_existing(*data)", source)


if __name__ == "__main__":
    unittest.main()
