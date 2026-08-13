# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
import json
from pathlib import Path
from PyQt6.QtWidgets import QListWidget, QListWidgetItem
from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QDrag

class AgentPalette(QListWidget):
    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setSelectionMode(self.SelectionMode.SingleSelection)

        # Use agents_meta as source of truth
        base_dir = Path(__file__).resolve().parents[2]  # matrix_gui/swarm_workspace
        self.agents_root = base_dir / "agents_meta"
        self.load_agents()

    def load_agents(self):
        self.clear()

        if not self.agents_root.exists():
            print(f"[PALETTE][WARN] agents_meta not found: {self.agents_root}")
            return

        candidates = list(self.agents_root.glob("*.json"))
        print(f"[PALETTE] 🔍 Found {len(candidates)} meta.json files under {self.agents_root}")

        for meta_path in candidates:

            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[PALETTE][ERROR] {meta_path}: {e}")
                continue

            if meta.get("name") == "matrix":
                continue  # Hide Matrix from palette

            name = meta.get("name") or meta_path.stem
            emoji = (
                meta.get("config", {})
                .get("ui", {})
                .get("agent_tree", {})
                .get("emoji", "")
            )
            label = f"{emoji} {name}" if emoji else name

            item = QListWidgetItem(label)
            meta["folder_name"] = meta_path.stem
            item.setData(Qt.ItemDataRole.UserRole, meta)
            self.addItem(item)

        print(f"[PALETTE] Loaded {self.count()} agents from agents_meta.")

    def mouseMoveEvent(self, event):
        item = self.currentItem()
        if not item:
            return
        mime = QMimeData()
        meta = item.data(Qt.ItemDataRole.UserRole)
        folder_name = meta.get("folder_name") or meta.get("name")
        mime.setText(folder_name)

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)
