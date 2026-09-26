"""Registry staging/rollback without a GUI, vault or external connection."""
from copy import deepcopy
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phoenix"))
from matrix_gui.modules.vault.vault_stores.registry_store import RegistryStore


class Root:
    def __init__(self):
        self.data = {"registry": {"ssh": {"original": {"label": "Original"}}, "other": {"keep": {}}}}
        self.outcome = True

    def get_section(self, key):
        return self.data.setdefault(key, {})

    def patch(self, key, value):
        # Emulate a root that can replace the live section before returning.
        self.data[key] = deepcopy(value)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class RegistryRollbackTests(unittest.TestCase):
    def setUp(self):
        # Store diagnostics contain Unicode; these tests exercise transactions,
        # independently of the host terminal's legacy code page.
        self.enterContext(redirect_stdout(io.StringIO()))

    def test_false_commit_restores_all_registry_data_and_buffer(self):
        root = Root()
        store = RegistryStore(root)
        before = deepcopy(root.data)
        root.outcome = False
        self.assertFalse(store.set_namespace("ssh", {"changed": {}}))
        self.assertEqual(before, root.data)
        self.assertIs(store._buffer, store.get_data())

    def test_exception_restores_state_then_propagates(self):
        root = Root()
        store = RegistryStore(root)
        before = deepcopy(root.data)
        root.outcome = RuntimeError("synthetic rejection")
        with self.assertRaises(RuntimeError):
            store.set_namespace("ssh", {})
        self.assertEqual(before, root.data)
        self.assertIs(store._buffer, store.get_data())

    def test_real_validation_rejection_restores_state(self):
        root = Root()
        store = RegistryStore(root)
        before = deepcopy(root.data)
        self.assertFalse(store.set_namespace("ssh", ["invalid namespace"]))
        self.assertEqual(before, root.data)

    def test_success_resynchronizes_buffer_and_copies_input(self):
        root = Root()
        store = RegistryStore(root)
        candidate = {"new": {"label": "new"}}
        self.assertTrue(store.set_namespace("ssh", candidate))
        candidate["new"]["label"] = "mutated caller"
        self.assertEqual("new", store.get_namespace("ssh")["new"]["label"])
        self.assertIs(store._buffer, store.get_data())
        self.assertEqual({"keep": {}}, store.get_namespace("other"))

    def test_later_success_does_not_commit_rejected_edit(self):
        root = Root()
        store = RegistryStore(root)
        root.outcome = False
        self.assertFalse(store.set_namespace("ssh", {"unwanted": {}}))
        root.outcome = True
        self.assertTrue(store.set_namespace("other", {"allowed": {}}))
        self.assertEqual({"original": {"label": "Original"}}, store.get_namespace("ssh"))


if __name__ == "__main__":
    unittest.main()
