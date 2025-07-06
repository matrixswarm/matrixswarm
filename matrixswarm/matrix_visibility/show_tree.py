import os
import json
from pathlib import Path

COMM_DIR = "/sites/orbit/python/comm"
DEPLOY_TREE_PATH = "/deploy/tree.json"


def load_delegates(universal_id):
    directive_path = os.path.join(COMM_DIR, universal_id, "directives")
    if not os.path.exists(directive_path):
        return []
    try:
        with open(directive_path, "r") as f:
            directives = json.load(f)
        return directives.get("delegated", [])
    except Exception as e:
        print(f" - Failed to read delegation for {universal_id}: {e}")
        return []


def build_tree_from_live():
    tree = {}
    for universal_id in os.listdir(COMM_DIR):
        path = os.path.join(COMM_DIR, universal_id)
        if not os.path.isdir(path):
            continue
        tree[universal_id] = load_delegates(universal_id)
    return tree


def build_tree_from_deploy():
    if not os.path.exists(DEPLOY_TREE_PATH):
        return {}
    try:
        with open(DEPLOY_TREE_PATH, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f" - Failed to load deploy tree: {e}")
        return {}


def print_tree(tree, root="matrix", indent=""):
    print(f"{indent}- {root}")
    for child in tree.get(root, []):
        print_tree(tree, child, indent + "  ")


def main():
    print("\n🌲 MATRIX DELEGATION TREE\n==========================")
    tree = build_tree_from_live()
    if not tree:
        print("[!] No active delegation found. Checking /deploy/tree.json...")
        tree = build_tree_from_deploy()
    if not tree:
        print("[!] No deployment tree available either.")
        return
    print_tree(tree)
    print("\nDone.\n")


if __name__ == "__main__":
    main()