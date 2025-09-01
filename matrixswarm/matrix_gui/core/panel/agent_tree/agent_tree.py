from matrix_gui.core.event_bus import EventBus
from matrix_gui.config.boot.globals import get_sessions
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QTreeWidget, QTreeWidgetItem, QSplitter
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QMovie

from matrix_gui.core.panel.agent_detail.agent_detail_panel import AgentDetailPanel
class PhoenixAgentTree(QWidget):
    def __init__(self, bound_session_id, vault_data=None, parent=None):
        super().__init__(parent)

        self.bound_session_id = bound_session_id
        self.vault_data = vault_data or {}

        self.layout = QVBoxLayout()
        self.splitter = QSplitter(Qt.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Agent"])
        self.tree.setColumnCount(1)
        self.tree.setStyleSheet("""
                   QTreeWidget::item { font-size: 13px; }
                   QTreeWidget { font-family: 'Segoe UI', Arial, sans-serif; }
               """)

        self.detail_panel = AgentDetailPanel()
        self.splitter.addWidget(self.tree)
        self.splitter.addWidget(self.detail_panel)
        self.layout.addWidget(self.splitter)

        self.tree.itemClicked.connect(self._on_tree_item_clicked)

        self.setLayout(self.layout)
        self.tree.setVisible(True)
        self.detail_panel.setVisible(True)
        self.splitter.setSizes([300, 200])


        self.spinner_label = QLabel()
        self.spinner_movie = QMovie("assets/spinner.gif")
        self.layout.addWidget(self.spinner_label)



        self._expanded_nodes = set()
        self.tree.itemExpanded.connect(self._track_expanded)
        self.tree.itemCollapsed.connect(self._track_collapsed)


        # subscribe to bus
        EventBus.on("inbound.verified.agent_tree_master.update", self._on_inbound)

    def _track_expanded(self, item):
        uid = item.text(0)  # Adjust the column as needed (likely Agent name)
        self._expanded_nodes.add(uid)

    def _track_collapsed(self, item):
        uid = item.text(0)
        self._expanded_nodes.discard(uid)

    def _on_inbound(self, session_id, channel, source, payload, **_):

        if session_id == self.bound_session_id and payload.get("handler") == "agent_tree_master.update":
            tree_data = payload.get("content", {})

            self._render_tree(tree_data)

    def _on_tree_item_clicked(self, item, column):
        node_data = item.data(0, Qt.UserRole)
        if node_data:
            self.detail_panel.set_agent_data(node_data)

    def _build_node(self, parent_item, node):
        name = node.get("name", "?")
        status = node.get("agent_status", {})
        threads = status.get("threads", {})
        spawn = status.get("spawn", {})

        icons = []
        for thread, state in threads.items():
            symbol = state.split()[0]
            if symbol == "✅":
                icons.append("●")  # healthy (can be styled green for all, or left black)
            elif symbol == "😴":
                icons.append("○")  # sleeping
            elif symbol == "⚠️":
                icons.append("▲")  # warning (yellow if styled globally)
            elif symbol == "💥":
                icons.append("■")  # failure

        if spawn:
            icons.append("☢" if spawn.get("flip_tripping") else "·")

        display_text = f"{name}  {' '.join(icons)}"

        item = QTreeWidgetItem([display_text])
        item.setData(0, Qt.UserRole, node)
        parent_item.addChild(item)
        for child in node.get("children", []):
            self._build_node(item, child)

    def _format_display(self, node: dict) -> str:
        name = node.get("name", "?")
        status = node.get("agent_status", {})
        threads = status.get("threads", {})
        spawn = status.get("spawn", {})

        parts = []
        for t, state in threads.items():
            parts.append(f"{t}:{state}")  # full desc from Matrix (emoji + delta)

        if spawn:
            parts.append(f"⚡{spawn.get('count', 0)}")
            if spawn.get("flip_tripping"):
                parts.append("☢")

        return f"{name}  {' | '.join(parts)}"

    def _sync_node(self, parent_item, node: dict):
        uid = node.get("universal_id")
        # look for existing child
        match = None
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            if child.data(0, Qt.UserRole + 1) == uid:
                match = child
                break

        if not match:
            match = QTreeWidgetItem(parent_item)
            parent_item.addChild(match)
            match.setData(0, Qt.UserRole + 1, uid)

        # update label + payload
        display_text = self._format_display(node)
        if match.text(0) != display_text:
            match.setText(0, display_text)
        match.setData(0, Qt.UserRole, node)

        # recurse
        existing_ids = set()
        for child_node in node.get("children", []):
            cid = child_node.get("universal_id")
            existing_ids.add(cid)
            self._sync_node(match, child_node)

        # prune missing
        for i in reversed(range(match.childCount())):
            child = match.child(i)
            if child.data(0, Qt.UserRole + 1) not in existing_ids:
                match.removeChild(child)

    def _render_tree(self, tree: dict):
        if not isinstance(tree, dict):
            return
        root = self.tree.invisibleRootItem()
        self._sync_node(root, tree)
