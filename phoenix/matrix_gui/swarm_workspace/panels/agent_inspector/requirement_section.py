# Commander Edition – AgentInspector Requirement Section
# integrate this into agent_inspector.py or similar

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem
)
from matrix_gui.registry.registry_manager import RegistryManagerDialog

class RequirementSection(QWidget):
    """
    Handles viewing, adding, editing, and removing requirements on an agent node.
    Each requirement = {"class": "discord", "serial": "discord_123"}
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_agent = None
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("<b>Requirements</b>"))
        self.btn_add = QPushButton("+ Add Requirement")
        self.btn_add.clicked.connect(self._add_requirement)
        header_row.addWidget(self.btn_add)
        header_row.addStretch()
        self.layout.addLayout(header_row)

        self.req_list = QListWidget()
        self.layout.addWidget(self.req_list)

        self.btn_edit = QPushButton("✏️ Edit Selected")
        self.btn_edit.clicked.connect(self._edit_selected)
        self.btn_remove = QPushButton("🗑 Remove Selected")
        self.btn_remove.clicked.connect(self._remove_selected)

        row = QHBoxLayout()
        row.addWidget(self.btn_edit)
        row.addWidget(self.btn_remove)
        row.addStretch()
        self.layout.addLayout(row)

    # ------------------------------------------------------------
    def load_agent(self, agent_node: dict):
        """Reload the list of requirements for a given agent."""
        self.current_agent = agent_node
        self.refresh_list()

    def refresh_list(self):
        self.req_list.clear()
        if not self.current_agent:
            return
        for req in self.current_agent.get("constraints", []):
            cls = req.get("class", "unknown")
            serial = req.get("serial", "—")
            item = QListWidgetItem(f"{cls} → {serial}")
            item.setData(0, req)
            self.req_list.addItem(item)

    # ------------------------------------------------------------
    def _add_requirement(self):
        """Open RegistryManagerDialog unlocked to all classes."""
        if not self.current_agent:
            return

        def on_assign(cls_name, serial):
            new_req = {"class": cls_name, "serial": serial}
            self.current_agent.setdefault("constraints", []).append(new_req)
            self.refresh_list()

        dlg = RegistryManagerDialog(
            parent=self,
            class_lock=None,          # all classes visible
            assign_callback=on_assign
        )
        dlg.exec()

    def _edit_selected(self):
        """Edit an existing requirement (class locked)."""
        if not self.current_agent:
            return
        item = self.req_list.currentItem()
        if not item:
            return
        req = item.data(0)
        cls_name = req.get("class")

        def on_assign(cls_name_new, serial):
            # replace serial only (same class)
            req["serial"] = serial
            self.refresh_list()

        dlg = RegistryManagerDialog(
            parent=self,
            class_lock=cls_name,       # LOCKED to that one class
            assign_callback=on_assign
        )
        dlg.exec()

    def _remove_selected(self):
        if not self.current_agent:
            return
        idx = self.req_list.currentRow()
        if idx < 0:
            return
        self.current_agent["constraints"].pop(idx)
        self.refresh_list()
