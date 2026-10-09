# Authored by Daniel F MacDonald and ChatGPT-5.1 aka The Generals
import json
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QDrag
from .agent_catalog import agent_catalog_root, agent_tooltip, catalog_values

class AgentPalette(QListWidget):
    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setSelectionMode(self.SelectionMode.SingleSelection)

        # Use agents_meta as source of truth
        self.agents_root = agent_catalog_root()
        self.load_agents()

    def load_agents(self):
        self.clear()

        if not self.agents_root.exists():
            print(f"[PALETTE][WARN] agents_meta not found: {self.agents_root}")
            return

        candidates = sorted(self.agents_root.glob("*.json"))
        print(f"[PALETTE] 🔍 Found {len(candidates)} meta.json files under {self.agents_root}")

        for meta_path in candidates:

            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[PALETTE][ERROR] {meta_path}: {e}")
                continue

            if not isinstance(meta, dict):
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
            item.setToolTip(agent_tooltip(meta))
            meta["folder_name"] = meta_path.stem
            item.setData(Qt.ItemDataRole.UserRole, meta)
            self.addItem(item)

        print(f"[PALETTE] Loaded {self.count()} agents from agents_meta.")

    def filter_agents(self, *, keywords=(), group="", text=""):
        selected = {value.casefold() for value in keywords}
        text = text.strip().casefold()
        visible = 0
        for index in range(self.count()):
            item = self.item(index)
            meta = item.data(Qt.ItemDataRole.UserRole)
            words = catalog_values(meta, "keywords")
            groups = catalog_values(meta, "groups")
            haystack = " ".join([str(meta.get("name", "")),
                                 str(meta.get("description", "")), *words, *groups]).casefold()
            matches = ((not selected or bool(selected & words))
                       and (not group or group.casefold() in groups)
                       and (not text or text in haystack))
            item.setHidden(not matches)
            if not matches and item.isSelected():
                item.setSelected(False)
            visible += int(matches)
        return visible

    def mouseMoveEvent(self, event):
        item = self.currentItem()
        if not item or item.isHidden():
            return
        mime = QMimeData()
        meta = item.data(Qt.ItemDataRole.UserRole)
        folder_name = meta.get("folder_name") or meta.get("name")
        mime.setText(folder_name)

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class AgentPalettePanel(QWidget):
    """Filter catalog entries without changing the agents already on the canvas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.palette = AgentPalette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("Agent picker"))
        clear = QPushButton("Clear filters")
        clear.setAutoDefault(False)
        clear.clicked.connect(self.clear_filters)
        heading.addWidget(clear)
        layout.addLayout(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find agents…")
        self.search.setAccessibleName("Find agents")
        layout.addWidget(self.search)
        self.group = QComboBox()
        self.group.setAccessibleName("Agent group")
        self.group.addItem("All groups", "")
        self.keywords = QListWidget()
        self.keywords.setAccessibleName("Keywords; select any to match")
        self.keywords.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.keywords.setViewMode(QListWidget.ViewMode.IconMode)
        self.keywords.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.keywords.setMovement(QListWidget.Movement.Static)
        self.keywords.setSpacing(4)
        self.keywords.setMinimumHeight(80)
        self.keywords.setMaximumHeight(140)
        self.keywords.setToolTip("Click keywords to toggle them. An agent matching any selected keyword is shown within the selected group.")
        groups, words = set(), set()
        for index in range(self.palette.count()):
            meta = self.palette.item(index).data(Qt.ItemDataRole.UserRole)
            groups.update(catalog_values(meta, "groups"))
            words.update(catalog_values(meta, "keywords"))
        for group in sorted(groups):
            self.group.addItem(group.replace("_", " ").title(), group)
        for word in sorted(words):
            item = QListWidgetItem(word)
            item.setData(Qt.ItemDataRole.UserRole, word)
            self.keywords.addItem(item)
        layout.addWidget(self.group)
        layout.addWidget(QLabel("Keywords — match any (OR)"))
        layout.addWidget(self.keywords)
        self.results = QLabel()
        layout.addWidget(self.results)
        layout.addWidget(self.palette, 1)
        self.search.textChanged.connect(self.apply_filters)
        self.group.currentIndexChanged.connect(self.apply_filters)
        self.keywords.itemSelectionChanged.connect(self.apply_filters)
        self.apply_filters()

    def apply_filters(self, *_args):
        visible = self.palette.filter_agents(
            keywords=[item.data(Qt.ItemDataRole.UserRole) for item in self.keywords.selectedItems()],
            group=self.group.currentData() or "", text=self.search.text(),
        )
        self.results.setText(f"{visible} of {self.palette.count()} agents")

    def clear_filters(self):
        self.search.clear()
        self.group.setCurrentIndex(0)
        self.keywords.clearSelection()
        self.apply_filters()
