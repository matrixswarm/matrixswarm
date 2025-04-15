import os
import json
from collections import defaultdict

class DirectiveCleaner:
    def __init__(self, directive_path):
        self.directive_path = directive_path
        self.cleaned_tree = {}

    def load(self):
        try:
            with open(self.directive_path, "r") as f:
                self.tree = json.load(f)
            return True
        except Exception as e:
            print(f"[CLEANER] Failed to load directive: {e}")
            self.tree = {}
            return False

    def deduplicate(self):
        # Ensure one entry per permanent_id
        seen = {}
        unique_entries = []

        for entry in self.tree.get("agents", []):
            perm_id = entry.get("permanent_id")
            if perm_id and perm_id not in seen:
                seen[perm_id] = entry
                unique_entries.append(entry)
            else:
                print(f"[CLEANER] Removing duplicate for perm_id: {perm_id}")

        self.cleaned_tree = {"agents": unique_entries}

    def save(self):
        try:
            with open(self.directive_path, "w") as f:
                json.dump(self.cleaned_tree, f, indent=4)
            print("[CLEANER] Book of Life cleaned and saved.")
        except Exception as e:
            print(f"[CLEANER] Failed to save cleaned directive: {e}")
