"""Workspace CRUD and rejected commits, using synthetic in-memory data."""
from copy import deepcopy
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from matrix_gui.modules.vault.vault_stores.workplace_store import WorkspaceStore


class Root:
    def __init__(self):
        self.data = {"workspaces": {"one": {"label": "Original", "data": [], "meta": {"keep": 1}}}}
        self.outcome = True

    def get_section(self, key):
        return self.data.setdefault(key, {})

    def patch(self, key, value):
        self.data[key] = deepcopy(value)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class WorkspaceStoreTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.root = Root()
        self.store = WorkspaceStore(self.root)

    def test_read_is_detached_and_list_works(self):
        self.store.get_workspace("one")["data"].append("not saved")
        self.assertEqual(self.store.get_workspace("one")["data"], [])
        self.assertEqual(self.store.list_workspaces(), [("one", "Original")])

    def test_update_copies_input_and_merges_metadata(self):
        patch = {"label": "Changed", "meta": {"new": []}}
        self.assertTrue(self.store.update_workspace("one", patch))
        patch["meta"]["new"].append("external")
        self.assertEqual(self.store.get_workspace("one")["meta"], {"keep": 1, "new": []})
        self.assertIs(self.store._buffer, self.store.get_data())

    def test_delete_and_missing_delete(self):
        self.assertTrue(self.store.delete_workspace("one"))
        self.assertFalse(self.store.delete_workspace("one"))
        self.assertEqual(self.store.list_workspaces(), [])

    def test_rejected_and_throwing_commits_restore_state(self):
        for operation in ("update", "delete"):
            for outcome in (False, RuntimeError("synthetic failure")):
                with self.subTest(operation=operation, outcome=outcome):
                    before = deepcopy(self.root.data)
                    self.root.outcome = outcome
                    def action():
                        if operation == "update":
                            return self.store.update_workspace("one", {"label": "Rejected"})
                        return self.store.delete_workspace("one")
                    if isinstance(outcome, Exception):
                        with self.assertRaises(RuntimeError):
                            action()
                    else:
                        self.assertFalse(action())
                    self.assertEqual(self.root.data, before)
                    self.assertIs(self.store._buffer, self.store.get_data())

    def test_validation_rejection_does_not_leak_into_later_save(self):
        self.assertFalse(self.store.update_workspace("invalid", {"label": "No data"}))
        self.assertTrue(self.store.update_workspace("one", {"label": "Accepted"}))
        self.assertNotIn("invalid", self.root.data["workspaces"])


if __name__ == "__main__":
    unittest.main()
