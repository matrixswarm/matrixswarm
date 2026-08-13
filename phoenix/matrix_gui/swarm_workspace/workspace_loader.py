# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
# Loads workspace JSON into scene, restoring agents + meta

# Commander Edition Workspace Loader — AgentNode Based

import json
from pathlib import Path
from .autoplant import autoplant
from .migration_bootstrap import migrate_node_to_new_schema


def load_workspace(scene, agents_root, workspace_data):
    if not workspace_data:
        return

    scene.clear()
    controller = scene.workspace.controller

    # Reset controller state
    controller.nodes.clear()
    controller.edges.clear()

    nodes = workspace_data.get("data", [])
    spawned_items = []

    # --- 1) Spawn all nodes --------------------------------------------------
    for saved in nodes:
        name = saved["name"]
        meta_path = Path(agents_root) / f"{name}.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"name": name}

        saved = migrate_node_to_new_schema(saved, meta)

        # autoplant attaches the node object
        item = autoplant(scene, meta, saved=saved)
        controller.register_item(item)
        spawned_items.append(item)

    # --- 2) Normalize parent links -------------------------------------------
    # Fix legacy 'matrix' literal parents
    controller._normalize_parent_ids()

    # Attach orphans to Matrix automatically
    controller.normalize_orphans()

    # --- 3) Visual / structural rebuild --------------------------------------
    controller.relayout()
    controller.redraw_edges()

