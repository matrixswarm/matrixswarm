"""Restart/delete subtree nodes must not share mutable transaction state."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matrixos"))
from core.python_core.tree_parser import TreeParser


class TreeLifecycleIsolationTests(unittest.TestCase):
    def test_marked_subtree_has_independent_stage_and_snapshot(self):
        root = {"universal_id": "matrix", "children": [
            {"universal_id": "parent", "children": [
                {"universal_id": "one", "children": []},
                {"universal_id": "two", "children": []},
            ]}
        ]}
        tree = TreeParser(root)
        tree.reparse()
        mark = {"lifecycle_status": {"transaction_id": "tx", "op_stage": "shutdown_probe",
                                     "reap_target": [], "locked": {"reason": "restart"}}}
        self.assertEqual(set(tree.mark_target_list("parent", mark)), {"parent", "one", "two"})
        first = tree.get_node("one")["lifecycle_status"]
        second = tree.get_node("two")["lifecycle_status"]
        first["op_stage"] = "restart_start"
        first["reap_target"].append({"pod": "first"})
        first["locked"]["reason"] = "changed"
        self.assertEqual(second["op_stage"], "shutdown_probe")
        self.assertEqual(second["reap_target"], [])
        self.assertEqual(second["locked"]["reason"], "restart")
        self.assertEqual(mark["lifecycle_status"]["reap_target"], [])


if __name__ == "__main__":
    unittest.main()
