# Authored by Daniel F MacDonald and ChatGPT aka The Generals
# SourceControlPanel: replace an agent’s source and optionally restart it.

from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QLabel, QComboBox,
    QPushButton, QMessageBox
)
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class SourceControlPanel(QGroupBox):
    def __init__(self, session_id, bus, agent_tree=None, parent=None):
        super().__init__("🛠 Agent Source Control", parent)
        try:
            self.session_id = session_id
            self.bus = bus
            self.agent_tree = agent_tree  # hook into PhoenixAgentTree for available agents

            layout = QVBoxLayout()
            self.setLayout(layout)

            # Dropdown of available agents
            self.agent_selector = QComboBox()
            self.agent_selector.setEditable(True)
            layout.addWidget(QLabel("🎯 Select Agent"))
            layout.addWidget(self.agent_selector)

            # Replace Source button
            self.replace_btn = QPushButton("♻️ Replace Source")
            self.replace_btn.clicked.connect(self._replace_source)
            layout.addWidget(self.replace_btn)

            self.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #00ff66;
                    margin-top: 6px;
                    padding: 6px;
                    font-weight: bold;
                    color: #33ff33;
                }
                QLabel { color: #33ff33; }
                QComboBox, QPushButton, QCheckBox {
                    background-color: #000;
                    color: #33ff33;
                    border: 1px solid #00ff66;
                }
            """)

            # Subscribe to tree updates so we can refresh agent list
            if self.bus:
                self.bus.on(
                    f"inbound.verified.agent_tree_master.update",
                    self._update_agent_list
                )

        except Exception as e:
            emit_gui_exception_log("SourceControlPanel.__init__", e)

    def _update_agent_list(self, payload, **_):
        """Refresh dropdown with agent IDs from PhoenixAgentTree updates."""
        try:
            content = payload.get("content", {})
            agents = []

            def recurse(node):
                if not isinstance(node, dict):
                    return
                uid = node.get("universal_id")
                if uid:
                    agents.append(uid)
                for child in node.get("children", []):
                    recurse(child)

            recurse(content)

            self.agent_selector.clear()
            self.agent_selector.addItems(sorted(agents))
        except Exception as e:
            emit_gui_exception_log("SourceControlPanel._update_agent_list", e)

    def _replace_source(self):
        QMessageBox.information(
            self, "Replace Source",
            "Use Replace Source on the session toolbar to publish the server-wide source "
            "with this deployment's recorded administrator SSH profile."
        )
