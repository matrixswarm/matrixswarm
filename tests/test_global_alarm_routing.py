"""Exercise workspace role configuration and committed deployment refresh."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from PyQt6.QtWidgets import QApplication
from matrix_gui.core.event_bus import EventBus
from matrix_gui.core.phoenix_control_panel import PhoenixControlPanel
from matrix_gui.modules.railgun.deployment_cleanup import prepare_cleanup
from matrix_gui.swarm_workspace.cls_lib.agent.config_editors.global_alarm import GlobalAlarm


class Node:
    def __init__(self):
        self.config = {"interval_sec": 5, "alert_role": "hive.alert", "service-manager": [
            {"role": ["hive.global_alarm.get@cmd_get_alarms", "hive.global_alarm.update@cmd_update_alarms"],
             "scope": ["parent", "any"], "priority": {"default": 10}},
            {"role": ["other@cmd_other"], "scope": ["any"]}]}
        self._dirty = False
    def get_name(self): return "global_alarm"
    def mark_dirty(self): self._dirty = True


class FakeVault:
    def __init__(self):
        common = {"universe": "home", "railgun_target_identity": {"host": "192.0.2.1"}}
        self.data = {"deployments": {"old": dict(common, label="home", deployed_at="2026-01-01"),
                                      "new": dict(common, label="home", deployed_at="2026-02-01"),
                                      "other": {"label": "backup", "deployed_at": "2025-01-01"}}}
    def read(self): return deepcopy(self.data)
    def transform_section(self, section, transform):
        candidate = transform(deepcopy(self.data[section]))
        EventBus.emit("vault.update", data={section: candidate})
        self.data[section] = deepcopy(candidate)
        EventBus.emit("vault.core.update")
        return True


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def test_editor_saves_default_and_inbound_roles_without_discarding_metadata(self):
        node = Node()
        dialog = GlobalAlarm(node)
        self.addCleanup(dialog.deleteLater)
        dialog.alert_role.setText("hive.calendar")
        dialog.roles_list.addItem("hive.global_alarm.extra@cmd_extra")
        dialog._save()
        self.assertTrue(node._dirty)
        self.assertEqual(node.config["alert_role"], "hive.calendar")
        self.assertEqual(node.config["service-manager"][0]["priority"], {"default": 10})
        self.assertIn("hive.global_alarm.extra@cmd_extra", node.config["service-manager"][0]["role"])
        self.assertEqual(node.config["service-manager"][1]["role"], ["other@cmd_other"])

    def test_cleanup_refreshes_only_after_commit_and_preserves_selection_when_possible(self):
        vault = FakeVault()
        with patch("matrix_gui.modules.vault.services.vault_core_singleton.VaultCoreSingleton.get", return_value=vault):
            panel = PhoenixControlPanel()
            self.addCleanup(panel.deleteLater)
            self.addCleanup(EventBus.off, "vault.unlocked", panel.on_vault_unlocked)
            self.addCleanup(EventBus.off, "vault.core.update", panel.on_vault_update)
            panel.refresh_deployments()
            self.assertEqual(panel.deployment_selector.count(), 3)
            panel.deployment_selector.setCurrentIndex(panel.deployment_selector.findData("other"))
            finish = prepare_cleanup(vault, "new", True)
            self.assertEqual(finish(), 1)
            ids = [panel.deployment_selector.itemData(i) for i in range(panel.deployment_selector.count())]
            self.assertEqual(set(ids), {"new", "other"})
            self.assertEqual(panel.deployment_selector.currentData(), "other")
            vault.data["deployments"]["newer"] = {"label": "newer", "deployed_at": "2026-03-01"}
            EventBus.emit("vault.core.update")
            self.assertEqual(panel.deployment_selector.currentData(), "newer")

if __name__ == "__main__": unittest.main()
