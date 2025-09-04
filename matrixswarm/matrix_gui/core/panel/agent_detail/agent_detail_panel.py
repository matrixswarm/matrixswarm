from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QHBoxLayout, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer
import json, time

class AgentDetailPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)

        # === Agent Inspector ===
        self.inspector_group = QGroupBox("Agent Inspector")
        self.inspector_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        inspector_layout = QVBoxLayout(self.inspector_group)

        # Agent Info
        self.name_label = QLabel("Agent: -")
        self.uid_label = QLabel("Universal ID: -")
        self.spawn_label = QLabel("Spawn: -")

        header = QVBoxLayout()
        header.addWidget(self.name_label)
        header.addWidget(self.uid_label)
        header.addWidget(self.spawn_label)
        inspector_layout.addLayout(header)

        # Threads Table
        self.thread_table = QTableWidget()
        self.thread_table.setColumnCount(3)
        self.thread_table.setHorizontalHeaderLabels(["Thread", "Status", "Delta"])
        self.thread_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.thread_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        inspector_layout.addWidget(QLabel("🧵 Threads"))
        inspector_layout.addWidget(self.thread_table)

        # Config JSON
        self.config_group = QGroupBox("⚙️ Config")
        config_layout = QVBoxLayout(self.config_group)

        self.config_text = QTextEdit()
        self.config_text.setReadOnly(True)
        config_layout.addWidget(self.config_text)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.export_btn = QPushButton("Copy JSON")
        self.export_btn.clicked.connect(self._copy_config)
        btn_row.addWidget(self.export_btn)
        config_layout.addLayout(btn_row)

        inspector_layout.addWidget(self.config_group)
        self.layout.addWidget(self.inspector_group)
        self.inspector_group.setVisible(False)

        self.current_config = {}

    def _copy_config(self):
        from PyQt5.QtWidgets import QApplication
        cb = QApplication.clipboard()
        cb.setText(json.dumps(self.current_config, indent=2))

    def _update_config_text(self):
        scrubbed = {
            k: ("********" if "token" in k.lower() or "cert" in k.lower() else v)
            for k, v in self.current_config.items()
        }
        self.config_text.setText(json.dumps(scrubbed, indent=2))

    def set_agent_data(self, node):
        self.name_label.setText(f"Agent: {node.get('name', '?')}")
        self.uid_label.setText(f"Universal ID: {node.get('universal_id', '?')}")
        spawn = node.get("agent_status", {}).get("spawn", {})
        count = spawn.get("count", "?")
        flip = spawn.get("flip_tripping", False)
        self.spawn_label.setText(f"Spawn Count: {count}   Flip-Tripping: {'YES' if flip else 'NO'}")

        self.thread_table.setRowCount(0)
        for i, (name, info) in enumerate(node.get("agent_status", {}).get("heartbeat", {}).items()):
            self.thread_table.insertRow(i)
            self.thread_table.setItem(i, 0, QTableWidgetItem(name))
            self.thread_table.setItem(i, 1, QTableWidgetItem("✅" if info.get("status") == "alive" else "❌"))
            delta = info.get("delta")
            self.thread_table.setItem(i, 2, QTableWidgetItem(f"{int(delta)}s" if delta else "?"))

        self.current_config = node.get("config", {})
        self._update_config_text()
