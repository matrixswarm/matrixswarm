# Commander Edition – Generate meta.json from phoenix directives
import json
import sys
import importlib.util
from pathlib import Path

from matrix_gui.swarm_workspace.migration_bootstrap import migrate_tags_to_constraints


# --------------------------------------------------------------------
# UTILITY: dynamic import of python "json-style" directive modules
# --------------------------------------------------------------------
def load_directive(py_path: Path):
    """Executes a directive file like phoenix-01.py and returns matrix_directive dict."""
    try:
        spec = importlib.util.spec_from_file_location(py_path.stem, py_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[py_path.stem] = module
        spec.loader.exec_module(module)
        directive = getattr(module, "matrix_directive", None)
        if directive:
            print(f"[DIRECTIVE] ✅ Loaded {py_path.name}")
            return directive
        else:
            print(f"[DIRECTIVE] ⚠️ {py_path.name} has no matrix_directive variable")
    except Exception as e:
        print(f"[DIRECTIVE] ❌ Failed to load {py_path.name}: {e}")
    return None


# --------------------------------------------------------------------
# RECURSIVE FLATTENER: collect all agent nodes in directive tree
# --------------------------------------------------------------------
def extract_nodes(tree):
    nodes = [tree]
    for child in tree.get("children", []):
        nodes.extend(extract_nodes(child))
    return nodes


# --------------------------------------------------------------------
# MAIN GENERATOR
# --------------------------------------------------------------------
def generate_meta_from_directives(
    directives_dir: Path,
    output_dir: Path,
):
    """
    Loads all phoenix-*.py directives from boot_directives/,
    extracts agent definitions, converts tags→constraints,
    and writes meta.json for each unique agent.
    """

    directives = []
    for file in directives_dir.glob("phoenix-*.py"):
        d = load_directive(file)
        if d:
            directives.append(d)

    if not directives:
        print(f"[META] ❌ No directives found under {directives_dir}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    seen = set()
    counter = 0

    for directive in directives:
        for node in extract_nodes(directive):
            name = node.get("name")
            if not name or name in seen:
                continue
            seen.add(name)

            migrate_tags_to_constraints(node)

            meta = {
                "name": name,
                "universal_id": node.get("universal_id", name),
                "constraints": node.get("constraints", []),
                "config": node.get("config", {}),
            }

            out_path = output_dir / f"{name}.json"
            out_path.write_text(json.dumps(meta, indent=4), encoding="utf-8")
            counter += 1
            print(f"[META] 🛰️  Generated {out_path}")

    print(f"[META] 🏁 Completed meta.json generation for {counter} agents.")


# --------------------------------------------------------------------
# CLI ENTRYPOINT
# --------------------------------------------------------------------
if __name__ == "__main__":
    base = Path(__file__).resolve().parents[3]  # matrix_gui/
    directives_dir = base / "boot_directives"
    output_dir = base / "agents_meta"

    generate_meta_from_directives(directives_dir, output_dir)
