from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QTreeWidget, QTreeWidgetItem,
    QSplitter, QHBoxLayout, QSizePolicy, QFrame, QLineEdit
)
from PyQt5.QtCore import Qt, QTimer
import json, time

class AgentDetailPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        # --- Agent Command Bar ---
        self.command_bar = QHBoxLayout()
        self.kill_btn = QPushButton("☠️ Kill")
        self.respawn_btn = QPushButton("🔁 Respawn")
        self.logs_btn = QPushButton("📜 Logs")
        self.status_light = QLabel("●")
        self.status_light.setStyleSheet("color: red; font-size: 14px;")
        self.command_bar.addWidget(self.kill_btn)
        self.command_bar.addWidget(self.respawn_btn)
        self.command_bar.addWidget(self.logs_btn)
        self.command_bar.addStretch()
        self.command_bar.addWidget(QLabel("Status:"))
        self.command_bar.addWidget(self.status_light)
        self.layout.addLayout(self.command_bar)

        # --- Splitter for Agent Info, Threads, Config ---
        self.detail_splitter = QSplitter(Qt.Vertical)
        self.layout.addWidget(self.detail_splitter)

        # --- Agent Info ---
        self.agent_info_widget = QWidget()
        self.agent_info_layout = QVBoxLayout(self.agent_info_widget)
        self.name_label = QLabel("Agent:")
        self.uid_label = QLabel("Universal ID:")
        self.spawn_label = QLabel("Spawn:")
        self.agent_info_layout.addWidget(self.name_label)
        self.agent_info_layout.addWidget(self.uid_label)
        self.agent_info_layout.addWidget(self.spawn_label)
        self.detail_splitter.addWidget(self.agent_info_widget)

        # --- Thread Table ---
        self.thread_table = QTableWidget()
        self.thread_table.setColumnCount(3)
        self.thread_table.setHorizontalHeaderLabels(["Thread", "Status", "Delta"])
        self.thread_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.detail_splitter.addWidget(self.thread_table)

        # --- Config Section ---
        self.config_widget = QWidget()
        self.config_layout = QVBoxLayout(self.config_widget)
        self.config_group = QGroupBox("Config (Hidden)")
        self.inner_config_layout = QVBoxLayout()
        self.config_text = QTextEdit()
        self.config_text.setReadOnly(True)
        self.config_text.setVisible(False)
        self.toggle_btn = QPushButton("Show Config")
        self.toggle_btn.clicked.connect(self._toggle_config)
        self.export_btn = QPushButton("Copy")
        self.export_btn.clicked.connect(self._copy_config)
        btns = QHBoxLayout()
        btns.addWidget(self.toggle_btn)
        btns.addWidget(self.export_btn)
        self.inner_config_layout.addLayout(btns)
        self.inner_config_layout.addWidget(self.config_text)
        self.config_group.setLayout(self.inner_config_layout)
        self.config_layout.addWidget(self.config_group)
        self.detail_splitter.addWidget(self.config_widget)

        # Agent Info - compact, fit content
        self.agent_info_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.agent_info_widget.setMinimumHeight(100)  # Adjust if needed

        # Thread Health - expands vertically, has priority
        self.thread_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.thread_table.setMinimumHeight(200)

        # Config - expands vertically
        self.config_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.config_widget.setMinimumHeight(150)

        # Set clear splitter stretch factors
        self.detail_splitter.setStretchFactor(0, 0)  # Agent Info fixed height
        self.detail_splitter.setStretchFactor(1, 3)  # Threads panel priority
        self.detail_splitter.setStretchFactor(2, 2)  # Config panel secondary priority

        self.layout.addStretch()

        # Initial splitter size distribution
        self.detail_splitter.setSizes([100, 300, 200])

        self.agent_info_widget.setMinimumHeight(100)


        self.config_shown = False
        self.current_config = {}

    def _toggle_config(self):
        self.config_shown = not self.config_shown

        # Only show/hide the text widget, not the whole group
        self.config_text.setVisible(self.config_shown)

        self.config_group.setTitle("Config (Visible)" if self.config_shown else "Config (Hidden)")
        self.toggle_btn.setText("Hide Config" if self.config_shown else "Show Config")
        self._update_config_text()

        # Adjust splitter weights, but never collapse the group entirely
        if self.config_shown:
            self.detail_splitter.setStretchFactor(1, 1)  # Threads
            self.detail_splitter.setStretchFactor(2, 3)  # Config
        else:
            self.detail_splitter.setStretchFactor(1, 1)
            self.detail_splitter.setStretchFactor(2, 0)  # Config shrinks, but group stays alive

    def _copy_config(self):
        from PyQt5.QtWidgets import QApplication
        cb = QApplication.clipboard()
        cb.setText(json.dumps(self.current_config, indent=2))

    def _update_config_text(self):
        config = self.current_config
        if not self.config_shown:
            config = {
                k: ("********" if "token" in k.lower() or "cert" in k.lower() else v)
                for k, v in config.items()
            }
        self.config_text.setText(json.dumps(config, indent=2))



    def set_agent_data(self, node):
        name = node.get("name", "?")
        uid = node.get("universal_id", "?")
        status = node.get("agent_status", {})
        spawn = status.get("spawn", {})
        threads = status.get("threads", {})
        config = node.get("config", {})

        self.current_config = config

        self.name_label.setText(f"Agent: {name}")
        self.uid_label.setText(f"Universal ID: {uid}")
        flip = spawn.get("flip_tripping", False)
        count = spawn.get("count", "?")
        self.spawn_label.setText(f"Spawn Count: {count}   Flip-Tripping: {'YES' if flip else 'NO'}")

        self.thread_table.setRowCount(0)
        for i, (t, desc) in enumerate(threads.items()):
            icon = desc.split()[0]  # ✅ ⚠️ 💥 etc.
            delta = "?"
            if "(" in desc:
                try:
                    delta = desc.split("(")[1].replace(")", "")
                except:
                    pass
            self.thread_table.insertRow(i)
            self.thread_table.setItem(i, 0, QTableWidgetItem(t))
            self.thread_table.setItem(i, 1, QTableWidgetItem(icon))
            self.thread_table.setItem(i, 2, QTableWidgetItem(delta))

        self._update_config_text()

        config = node.get("config", {})

        self.current_config = config
        self._update_config_text()


