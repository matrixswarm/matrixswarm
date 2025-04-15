# LiveTreeManager.py
import os
import json
import time

class BookOfLife:
    def __init__(self, matrix_uuid, core, pod_root="/sites/orbit/python/pod"):
        self.matrix_uuid = matrix_uuid
        self.core = core
        self.tree = {}
        self.path = os.path.join(pod_root, matrix_uuid, "live.json.enc")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "rb") as f:
                    decrypted = self.core.decrypt(f.read()).decode("utf-8")
                    self.tree = json.loads(decrypted)
            except Exception as e:
                print(f"[TREE-ERROR] Failed to load tree: {e}")

    def save(self):
        try:
            encoded = json.dumps(self.tree, indent=2).encode("utf-8")
            encrypted = self.core.encrypt(encoded)
            with open(self.path, "wb") as f:
                f.write(encrypted)
        except Exception as e:
            print(f"[TREE-ERROR] Failed to save tree: {e}")

    def update_agent(self, permanent_id, uuid, label, parent):
        self.tree[permanent_id] = {
            "uuid": uuid,
            "label": label,
            "parent": parent,
            "last_seen": time.time(),
            "status": "alive"
        }
        print(f"[TREE-UPDATE] {permanent_id} → {uuid} under {parent}")
        self.save()

    def mark_dead(self, permanent_id):
        if permanent_id in self.tree:
            self.tree[permanent_id]["status"] = "dead"
            self.tree[permanent_id]["last_seen"] = time.time()
            print(f"[TREE] Marked {permanent_id} as dead")
            self.save()

    def get_branch(self, permanent_id):
        return self.tree.get(permanent_id, None)

    def list_children(self, parent):
        return [pid for pid, data in self.tree.items() if data.get("parent") == parent]
