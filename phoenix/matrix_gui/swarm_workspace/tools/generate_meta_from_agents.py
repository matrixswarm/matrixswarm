# Builds new meta.json files for each MatrixOS agent

import json
from pathlib import Path
from matrix_gui.swarm_workspace.migration_bootstrap import (
    migrate_node_to_new_schema, migrate_tags_to_constraints
)

def generate_meta_for_agents(agents_root: Path, output_to_same_dir=True):
    """
    Scans all agent folders under agents_root.
    For each agent, reads any existing meta.json or constructs one based on folder name,
    then runs the full Commander migration, and writes out a clean meta.json.
    """

    if not agents_root.exists():
        print(f"[META][ERROR] Agents root not found: {agents_root}")
        return

    agent_dirs = [p for p in agents_root.iterdir() if p.is_dir()]

    for agent_dir in agent_dirs:
        name = agent_dir.name
        meta_path = agent_dir / "meta.json"

        # Load existing meta if present
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                print(f"[META] Loading existing meta.json for {name}")
            except Exception as e:
                print(f"[META][WARN] Failed to read meta for {name}: {e}")
                meta = {}
        else:
            # Build new minimal meta
            print(f"[META] Creating new meta.json for {name}")
            meta = {
                "name": name,
                "ui": {
                    "agent_tree": {"emoji": "🤖"}
                },
                "tags": {},
                "config": {}
            }

        # Convert to a node-like structure so we can use migration functions
        node = {
            "universal_id": meta.get("universal_id", name),
            "name": meta.get("name", name),
            "meta": meta,
            "tags": meta.get("tags", {}),
            "config": meta.get("config", {}),
            "params": meta.get("params", {}),
            "parent": None
        }

        # Run commander migration
        migrate_tags_to_constraints(node)       # old tags → new constraints
        node = migrate_node_to_new_schema(node, meta)

        # Build final meta.json payload (clean commander schema)
        final_meta = {
            "name": node["name"],
            "universal_id": node["universal_id"],
            "constraints": node["constraints"],
            "config": node.get("config", {}),
            "ui": meta.get("ui", {"agent_tree": {"emoji": "🤖"}})
        }

        # Save back into file
        out_path = meta_path if output_to_same_dir else (agent_dir / "meta.generated.json")
        out_path.write_text(json.dumps(final_meta, indent=4), encoding="utf-8")

        print(f"[META] ✔ Wrote: {out_path}")

    print("[META] 🏁 Completed meta.json generation for all agents.")
