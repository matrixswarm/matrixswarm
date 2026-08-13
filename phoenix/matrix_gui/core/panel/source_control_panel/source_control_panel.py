# Authored by Daniel F MacDonald and ChatGPT aka The Generals
# SourceControlPanel: replace an agent’s source and optionally restart it.

import os, base64, hashlib, time, json, shutil
from PyQt6.QtWidgets import (
    QGroupBox, QVBoxLayout, QLabel, QComboBox,
    QPushButton, QFileDialog, QCheckBox, QMessageBox
)
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet

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

            # Restart toggle
            self.restart_checkbox = QCheckBox("Restart agent after replace")
            self.restart_checkbox.setChecked(True)
            layout.addWidget(self.restart_checkbox)

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
        try:
            uid = self.agent_selector.currentText().strip()
            if not uid:
                QMessageBox.warning(self, "Missing Agent", "Select an agent to replace.")
                return

            file_name, _ = QFileDialog.getOpenFileName(self, "Select Replacement Source", "", "Python Files (*.py)")
            if not file_name:
                return

            with open(file_name, "rb") as f:
                code = f.read()
                encoded = base64.b64encode(code).decode("utf-8")
                file_hash = hashlib.sha256(code).hexdigest()

            deploy_data = {
                "name": uid,
                "hotswap": True,
                "config": {},
                "filesystem": {},
                "source_payload": {
                    "payload": encoded,
                    "sha256": file_hash
                }
            }

            payload = {
                "handler": "cmd_replace_source",
                "timestamp": time.time(),
                "content": {
                    "target_universal_id": uid,
                    "new_agent": deploy_data,
                    "restart": self.restart_checkbox.isChecked()
                }
            }

            # Emit outbound message to Matrix
            pk = Packet()
            pk.set_data(payload)
            self.bus.emit("outbound.message", session_id=self.session_id,
                          channel="outgoing.command", packet=pk)

            QMessageBox.information(self, "Success",
                                    f"Source replaced for {uid}\nSHA256: {file_hash[:12]}...")

        except Exception as e:
            emit_gui_exception_log("SourceControlPanel._replace_source", e)
