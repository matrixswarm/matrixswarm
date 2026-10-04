"""Synthetic Vault-only tests for Terminal access policy authoring."""

from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phoenix"))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from matrix_gui.core.panel.home.terminal_access_controls import TerminalAccessControls
from matrix_gui.core import startup_policy
from matrix_gui.modules.vault.terminal_access_policy import (
    TerminalAccessPolicyError,
    authorize_vault_operation,
    policy_from_vault,
    validate_policy,
    vault_revision,
)


def fixture():
    return {
        "deployments": {
            "alpha-on-host-a": {"label": "Alpha A", "agents": []},
            "alpha-on-host-b": {"label": "Alpha B", "agents": []},
        },
        "registry": {"synthetic": {"password": "TEST-ONLY-NOT-REAL"}},
        "workspaces": {},
    }


def policy(*, deployment_ids=("alpha-on-host-a",), enabled=True):
    return {
        "schema_version": 1,
        "enabled": enabled,
        "approval_lifetime_seconds": 900,
        "permissions": {
            "alerts.read": {
                "enabled": True,
                "deployment_ids": list(deployment_ids),
            }
        },
    }


class PolicyTests(unittest.TestCase):
    def test_new_operations_default_off_and_whitelists_are_independent(self):
        data = fixture()
        data["terminal_access"] = policy()
        self.assertFalse(authorize_vault_operation(data, "swarms.list", "alpha-on-host-a"))
        self.assertFalse(authorize_vault_operation(data, "railgun.launch", "alpha-on-host-a"))
        data["terminal_access"]["permissions"]["swarms.list"] = {"enabled": True, "deployment_ids": ["alpha-on-host-b"]}
        self.assertTrue(authorize_vault_operation(data, "swarms.list", "alpha-on-host-b"))
        self.assertFalse(authorize_vault_operation(data, "swarms.list", "alpha-on-host-a"))
        self.assertFalse(authorize_vault_operation(data, "railgun.launch", "alpha-on-host-b"))

    def test_missing_policy_is_off_and_exact_scoped_read_is_allowed(self):
        vault = fixture()
        self.assertFalse(authorize_vault_operation(vault, "alerts.read", "alpha-on-host-a"))
        vault["terminal_access"] = policy()
        self.assertTrue(authorize_vault_operation(vault, "alerts.read", "alpha-on-host-a"))
        self.assertFalse(authorize_vault_operation(vault, "alerts.read", "alpha-on-host-b"))
        self.assertFalse(authorize_vault_operation(vault, "alerts.list", "alpha-on-host-a"))

    def test_read_permission_does_not_imply_mutations_or_generic_actions(self):
        vault = fixture()
        vault["terminal_access"] = policy(deployment_ids=("alpha-on-host-a", "alpha-on-host-b"))
        for operation in (
            "alerts.ack",
            "alerts.delete",
            "alerts.mute",
            "agent.restart",
            "agent.config.set",
            "panel.call",
            "packet.send",
            "shell",
        ):
            with self.subTest(operation=operation):
                self.assertFalse(
                    authorize_vault_operation(vault, operation, "alpha-on-host-a")
                )

    def test_forged_unknown_fields_operations_and_foreign_ids_fail_closed(self):
        cases = []
        extra = policy()
        extra["allow_all"] = True
        cases.append(extra)
        unknown = policy()
        unknown["permissions"]["shell"] = {
            "enabled": True,
            "deployment_ids": ["alpha-on-host-a"],
        }
        cases.append(unknown)
        cases.append(policy(deployment_ids=("foreign",)))
        boolean_lifetime = policy()
        boolean_lifetime["approval_lifetime_seconds"] = True
        cases.append(boolean_lifetime)
        for record in cases:
            with self.subTest(record=record):
                vault = fixture()
                vault["terminal_access"] = record
                with self.assertRaises(TerminalAccessPolicyError):
                    policy_from_vault(vault)
                self.assertFalse(
                    authorize_vault_operation(vault, "alerts.read", "alpha-on-host-a")
                )

    def test_same_label_on_two_hosts_remains_two_exact_resource_ids(self):
        vault = fixture()
        vault["terminal_access"] = policy(deployment_ids=("alpha-on-host-b",))
        parsed = policy_from_vault(vault)
        self.assertEqual(
            ("alpha-on-host-b",),
            parsed.permissions["alerts.read"].deployment_ids,
        )
        self.assertFalse(authorize_vault_operation(vault, "alerts.read", "alpha-on-host-a"))
        self.assertTrue(authorize_vault_operation(vault, "alerts.read", "alpha-on-host-b"))

    def test_snapshot_revision_changes_for_policy_or_toolkit_change(self):
        original = fixture()
        first = vault_revision(original)
        changed_policy = deepcopy(original)
        changed_policy["terminal_access"] = policy()
        changed_toolkit = deepcopy(original)
        changed_toolkit["deployments"]["alpha-on-host-a"]["agents"].append(
            {"universal_id": "new-agent"}
        )
        self.assertNotEqual(first, vault_revision(changed_policy))
        self.assertNotEqual(first, vault_revision(changed_toolkit))
        self.assertEqual(first, vault_revision(deepcopy(original)))

    def test_empty_alert_scope_is_valid_but_grants_nothing(self):
        record = policy(deployment_ids=())
        parsed = validate_policy(record, ("alpha-on-host-a",))
        self.assertEqual((), parsed.permissions["alerts.read"].deployment_ids)


class FakeVaultAuthority:
    def __init__(self, data):
        self.data = deepcopy(data)
        self.patch_calls = []

    def read(self):
        return deepcopy(self.data)

    def patch(self, key, value):
        self.patch_calls.append((key, deepcopy(value)))
        self.data[key] = deepcopy(value)
        return True


class DashboardControlTests(unittest.TestCase):
    def test_independent_operation_columns_save_without_widening_alerts(self):
        authority = FakeVaultAuthority(fixture())
        controls = TerminalAccessControls(vault_authority=authority, terminal_mode=True)
        self.addCleanup(controls.deleteLater)
        controls.enabled_checkbox.setChecked(True)
        controls.swarms_checkbox.setChecked(True)
        controls.railgun_checkbox.setChecked(True)
        controls.deployment_scope.topLevelItem(0).setCheckState(2, Qt.CheckState.Checked)
        controls.deployment_scope.topLevelItem(1).setCheckState(3, Qt.CheckState.Checked)
        controls.save_policy()
        saved = authority.patch_calls[0][1]["permissions"]
        self.assertEqual(["alpha-on-host-a"], saved["swarms.list"]["deployment_ids"])
        self.assertEqual(["alpha-on-host-b"], saved["railgun.launch"]["deployment_ids"])
        self.assertFalse(saved["alerts.read"]["enabled"])
        controls.refresh_from_vault()
        self.assertIn("swarms.list: 1", controls.summary.text())
        self.assertIn("railgun.launch: 1", controls.summary.text())

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_controls_are_visible_only_in_terminal_mode(self):
        authority = FakeVaultAuthority(fixture())
        normal = TerminalAccessControls(vault_authority=authority, terminal_mode=False)
        record = TerminalAccessControls(vault_authority=authority, terminal_mode=True)
        self.addCleanup(normal.deleteLater)
        self.addCleanup(record.deleteLater)
        self.assertTrue(normal.isHidden())
        record.show()
        self.app.processEvents()
        self.assertTrue(record.isVisible())
        self.assertIn("does not start a listener", record.findChild(
            type(record.summary), "TerminalAccessExplanation"
        ).text())

    def test_refresh_does_not_enable_terminal_mode_outside_its_window(self):
        startup_policy.reset_startup_policy()
        self.addCleanup(startup_policy.reset_startup_policy)
        authority = FakeVaultAuthority(fixture())
        controls = TerminalAccessControls(vault_authority=authority)
        self.addCleanup(controls.deleteLater)
        self.assertTrue(controls.isHidden())
        controls.refresh_from_vault()
        self.assertTrue(controls.isHidden())

    def test_save_persists_exact_alert_scope_without_starting_runtime(self):
        authority = FakeVaultAuthority(fixture())
        controls = TerminalAccessControls(vault_authority=authority, terminal_mode=True)
        self.addCleanup(controls.deleteLater)
        controls.enabled_checkbox.setChecked(True)
        controls.alerts_checkbox.setChecked(True)
        item = controls.deployment_scope.topLevelItem(1)
        item.setCheckState(1, Qt.CheckState.Checked)
        controls.save_policy()
        self.assertEqual(1, len(authority.patch_calls))
        key, saved = authority.patch_calls[0]
        self.assertEqual("terminal_access", key)
        self.assertEqual(
            ["alpha-on-host-b"],
            saved["permissions"]["alerts.read"]["deployment_ids"],
        )
        self.assertNotIn("listener", saved)
        self.assertIn("No listener", controls.summary.text())

    def test_enabled_alert_read_without_scope_is_not_saved(self):
        authority = FakeVaultAuthority(fixture())
        controls = TerminalAccessControls(vault_authority=authority, terminal_mode=True)
        self.addCleanup(controls.deleteLater)
        controls.enabled_checkbox.setChecked(True)
        controls.alerts_checkbox.setChecked(True)
        controls.save_policy()
        self.assertEqual([], authority.patch_calls)
        self.assertIn("not saved", controls.summary.text())


if __name__ == "__main__":
    unittest.main()
