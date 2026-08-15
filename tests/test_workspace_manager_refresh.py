from pathlib import Path
import ast
import json
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_MANAGER = (
    ROOT
    / "phoenix/matrix_gui/swarm_workspace/workspace_manager.py"
)
MATRIX_META = ROOT / "phoenix/agents_meta/matrix.json"


def source(path):
    return path.read_text(encoding="utf-8")


def method_source(path, class_name, method_name):
    text = source(path)
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return ast.get_source_segment(text, child)
    raise AssertionError(f"{class_name}.{method_name} not found")


def load_method(path, class_name, method_name, globals_=None):
    text = source(path)
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    module = ast.Module(body=[child], type_ignores=[])
                    ast.fix_missing_locations(module)
                    namespace = dict(globals_ or {})
                    exec(compile(module, str(path), "exec"), namespace)
                    return namespace[method_name]
    raise AssertionError(f"{class_name}.{method_name} not found")


class WorkspaceManagerRefreshTests(unittest.TestCase):
    def test_source_compiles(self):
        text = source(WORKSPACE_MANAGER)
        compile(text, str(WORKSPACE_MANAGER), "exec")

    def test_matrix_metadata_is_strict_json(self):
        metadata = json.loads(source(MATRIX_META))
        self.assertEqual(metadata["name"], "matrix")
        self.assertEqual(metadata["universal_id"], "matrix")

    def test_new_workspace_refreshes_and_selects_before_open_signal(self):
        text = method_source(
            WORKSPACE_MANAGER,
            "WorkspaceManagerDialog",
            "_new_workspace",
        )

        persist = text.index("self._persist(updated_workspaces)")
        populate = text.index("self._populate()")
        select = text.index("self._select_workspace(ws_uuid)")
        emit = text.index("self.workspace_selected.emit(ws_uuid)")

        self.assertLess(persist, populate)
        self.assertLess(populate, select)
        self.assertLess(select, emit)

    def test_new_workspace_validates_metadata_before_vault_mutation(self):
        text = method_source(
            WORKSPACE_MANAGER,
            "WorkspaceManagerDialog",
            "_new_workspace",
        )

        load_metadata = text.index("matrix_meta = json.loads(")
        build_node = text.index("matrix_node = AgentNode(matrix_meta).get_node()")
        stage_workspace = text.index("updated_workspaces[ws_uuid] = new_workspace")
        persist = text.index("self._persist(updated_workspaces)")

        self.assertLess(load_metadata, build_node)
        self.assertLess(build_node, stage_workspace)
        self.assertLess(stage_workspace, persist)
        self.assertNotIn("self.workspaces[ws_uuid] =", text)

    def test_new_and_clone_share_workspace_selection_helper(self):
        new_text = method_source(
            WORKSPACE_MANAGER,
            "WorkspaceManagerDialog",
            "_new_workspace",
        )
        clone_text = method_source(
            WORKSPACE_MANAGER,
            "WorkspaceManagerDialog",
            "_clone_workspace",
        )

        self.assertIn("self._select_workspace(ws_uuid)", new_text)
        self.assertIn("self._select_workspace(new_uuid)", clone_text)

    def test_selection_helper_selects_matching_workspace_row(self):
        user_role = object()
        qt = SimpleNamespace(
            ItemDataRole=SimpleNamespace(UserRole=user_role),
        )
        select_workspace = load_method(
            WORKSPACE_MANAGER,
            "WorkspaceManagerDialog",
            "_select_workspace",
            {"Qt": qt},
        )

        class Item:
            def __init__(self, workspace_uuid):
                self.workspace_uuid = workspace_uuid

            def data(self, role):
                self.assert_role(role)
                return self.workspace_uuid

            @staticmethod
            def assert_role(role):
                if role is not user_role:
                    raise AssertionError("unexpected item-data role")

        class ListWidget:
            def __init__(self):
                self.items = [Item("alpha"), Item("bravo")]
                self.current_row = None

            def count(self):
                return len(self.items)

            def item(self, row):
                return self.items[row]

            def setCurrentRow(self, row):
                self.current_row = row

        list_widget = ListWidget()
        dialog = SimpleNamespace(ws_list=list_widget)

        self.assertTrue(select_workspace(dialog, "bravo"))
        self.assertEqual(list_widget.current_row, 1)
        self.assertFalse(select_workspace(dialog, "charlie"))


if __name__ == "__main__":
    unittest.main()
