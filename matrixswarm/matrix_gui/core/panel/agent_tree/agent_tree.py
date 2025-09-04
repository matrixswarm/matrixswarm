from matrix_gui.core.event_bus import EventBus
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy, QTreeWidget, QTreeWidgetItem
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QMovie
from matrix_gui.core.panel.agent_detail.agent_detail_panel import AgentDetailPanel


class PhoenixAgentTree(QWidget):
    def __init__(self, bound_session_id, vault_data=None, parent=None):
        super().__init__(parent)
        self.bound_session_id = bound_session_id
        self.vault_data = vault_data or {}

        self.layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Agent", "Spawns"])
        self.tree.setColumnCount(2)
        self.tree.setMinimumWidth(400)
        self.tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.tree.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.header().setStretchLastSection(True)

        self.layout.addWidget(self.tree, stretch=1)

        # Cleaned out old detail_panel here
        self.detail_panel = AgentDetailPanel()  # still exists, but used externally

        self.tree.itemClicked.connect(self._on_tree_item_clicked)
        EventBus.on("inbound.verified.agent_tree_master.update", self._on_inbound)

    def _on_tree_item_clicked(self, item, column):
        node_data = item.data(0, Qt.UserRole)
        if node_data:
            self.detail_panel.set_agent_data(node_data)

    def _on_inbound(self, session_id, channel, source, payload, **_):
        if session_id == self.bound_session_id and payload.get("handler") == "agent_tree_master.update":
            self._render_tree(payload.get("content", {}))

    def _render_tree(self, tree: dict):
        if not isinstance(tree, dict):
            return

        root = self.tree.invisibleRootItem()
        root.takeChildren()

        name, health = self._format_display(tree)
        root_item = QTreeWidgetItem([name, health])
        root_item.setData(0, Qt.UserRole, tree)
        root.addChild(root_item)

        for child in tree.get("children", []):
            self._build_node(root_item, child)

        self.tree.expandAll()

    def _build_node(self, parent_item, node):
        name, health = self._format_display(node)
        item = QTreeWidgetItem([name, health])
        item.setData(0, Qt.UserRole, node)
        parent_item.addChild(item)

        for child in node.get("children", []):
            self._build_node(item, child)

    def _format_display(self, node: dict):
        name = node.get("name", "unnamed")
        spawn = node.get("agent_status", {}).get("spawn", {})
        cnt = spawn.get("count", 0)
        symbol = f"⚡{cnt}" if cnt else ""
        return name, symbol
