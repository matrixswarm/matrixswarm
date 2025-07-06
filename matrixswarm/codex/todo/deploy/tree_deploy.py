import os
import json
from pathlib import Path

COMM_DIR = "/sites/orbit/python/comm"
DEPLOY_TREE_PATH = os.path.join(os.path.dirname(__file__), "tree.json")

def deploy_tree():
    if not os.path.exists(DEPLOY_TREE_PATH):
        print("[!] No tree.json found in deploy folder. Aborting.")
        return

    try:
        with open(DEPLOY_TREE_PATH, "r", encoding="utf-8") as f:
            tree = json.load(f)
    except Exception as e:
        print(f"[!] Failed to parse tree.json: {e}")
        return

    for universal_id, children in tree.items():
        path = os.path.join(COMM_DIR, universal_id)
        os.makedirs(path, exist_ok=True)
        directive_path = os.path.join(path, "directives")
        try:
            with open(directive_path, "w", encoding="utf-8") as f:
                json.dump({
                    "universal_id": universal_id,
                    "delegated": children
                }, f, indent=2)
            print(f"✅ Injected: {universal_id} → {children}")
        except Exception as e:
            print(f"❌ Failed to write {universal_id}: {e}")

    print("\n🌱 Tree deployed successfully from tree.json\n")


def print_tree(tree, root="matrix", indent=""):
    print(f"{indent}- {root}")
    for child in tree.get(root, []):
        print_tree(tree, child, indent + "  ")


def show_tree():
    tree = {}
    for universal_id in os.listdir(COMM_DIR):
        path = os.path.join(COMM_DIR, universal_id)
        if not os.path.isdir(path):
            continue
        directive_path = os.path.join(path, "directives")
        if not os.path.exists(directive_path):
            continue
        try:
            with open(directive_path, "r", encoding="utf-8") as f:
                directives = json.load(f)
            tree[universal_id] = directives.get("delegated", [])
        except Exception as e:
            print(f" - Failed to read {universal_id}: {e}")

    if not tree:
        print("[!] No live structure found. Checking local tree.json...")
        try:
            with open(DEPLOY_TREE_PATH, "r", encoding="utf-8") as f:
                tree = json.load(f)
        except Exception as e:
            print(f" - Failed to load deploy tree: {e}")
            return

    print("\n🌲 MATRIX DELEGATION TREE\n==========================")
    print_tree(tree)
    print("\nDone.\n")


if __name__ == "__main__":
    print("Choose mode:\n 1) Deploy tree.json to /comm\n 2) Show current delegation tree\n")
    mode = input("Enter 1 or 2: ").strip()
    if mode == "1":
        deploy_tree()
    elif mode == "2":
        show_tree()
    else:
        print("Invalid option. Aborting.")

