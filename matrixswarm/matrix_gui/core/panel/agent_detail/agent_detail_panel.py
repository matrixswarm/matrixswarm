# Authored by Daniel F MacDonald and ChatGPT aka The Generals
import datetime
from PyQt5.QtGui import QColor, QBrush
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QHBoxLayout, QSizePolicy
)
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtCore import Qt, QSize, QTimer
import json
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from PyQt5.QtWidgets import QApplication
class AgentDetailPanel(QWidget):
    def __init__(self, session_id, bus=None):
        super().__init__()


        try:
            self.bus=bus
            self.bound_session_id = session_id
            self.layout = QVBoxLayout(self)

            # === Agent Inspector ===
            self.inspector_group = QGroupBox("Agent Inspector")
            self.inspector_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            inspector_layout = QVBoxLayout(self.inspector_group)

            #Agent Detail
            self.label = QLabel("Agent: -  Universal ID: -  Spawn Count: -  Flip-Tripping: -")
            self.label.setStyleSheet("padding-top: 8px;padding-bottom: 4px;")

            self.inspector_group.layout().addWidget(self.label)

            # Threads Table
            self.thread_table = QTableWidget()
            self.thread_table.setColumnCount(3)
            self.thread_table.setHorizontalHeaderLabels(["Thread", "Status", "Delta"])
            self.thread_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.thread_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            inspector_layout.addWidget(QLabel("🧵 Threads & Processes"))
            inspector_layout.addWidget(self.thread_table)

            inspector_layout.addWidget(QLabel("🐣 Spawns"))
            self.spawn_table = QTableWidget()
            self.spawn_table.setColumnCount(2)
            self.spawn_table.setHorizontalHeaderLabels(["Timestamp", "Note"])
            self.spawn_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.spawn_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            inspector_layout.addWidget(self.spawn_table)





            self._closing = False

            # === Config JSON ===
            self.config_group = QGroupBox("⚙️ Config")
            self.config_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
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

            # Add both sections to the main panel
            self.layout.addWidget(self.inspector_group)
            self.layout.addWidget(self.config_group)

            self.layout.setStretch(1, 1)  # tree
            self.layout.setStretch(2, 2)  # panel

            self.inspector_group.setStyleSheet("QGroupBox { font-weight: bold; padding: 6px; margin-top: 8px; }")
            self.config_group.setStyleSheet("QGroupBox { font-weight: bold; padding: 6px; margin-top: 6px; }")
            self.inspector_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.config_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.current_config = {}

            self.bus.on(f"inbound.verified.agent_tree_master.update.{self.bound_session_id}", self._handle_tree_update)
            self.bus.on("gui.agent.selected", self.set_agent_data)

            #no agent selected
            self.current_uuid=""

        except Exception as e:
            emit_gui_exception_log("AgentDetailPanel._update_status_label", e)


    def sizeHint(self):
        h = 0
        if self.inspector_group.isVisible():
            h += self.inspector_group.sizeHint().height()
        if self.config_group.isVisible():
            h += self.config_group.sizeHint().height()
        return QSize(400, h if h else 0)

    def _copy_config(self):
        try:
            cb = QApplication.clipboard()
            cb.setText(json.dumps(self.current_config, indent=2))
        except Exception as e:
            emit_gui_exception_log("AgentDetailPanel._copy_config", e)

    def _handle_tree_update(self, payload, **_):

        try:
            content = payload.get("content", {})
            print(f"_handle_tree_update {self.current_uuid}")
            if not self.current_uuid:
                return

            # find the selected node in the updated tree
            def find_node(node, uid):
                if not isinstance(node, dict):
                    return None
                if node.get("universal_id") == uid:
                    return node
                for child in node.get("children", []):
                    found = find_node(child, uid)
                    if found:
                        return found
                return None

            node = find_node(content, self.current_uuid)
            if node:
                self.set_agent_data(node=node)
        except Exception as e:
            emit_gui_exception_log("AgentDetailPanel._handle_tree_update", e)

    def closeEvent(self, ev):
        self._closing = True
        super().closeEvent(ev)

    def _update_config_text(self):
        try:
            if self._closing:
                return
            scrubbed = {
                k: ("********" if "token" in k.lower() or "cert" in k.lower() else v)
                for k, v in self.current_config.items()
            }
            self.config_text.setText(json.dumps(scrubbed, indent=2))
        except Exception as e:
            emit_gui_exception_log("AgentDetailPanel._update_config_text", e)

    def set_agent_data(self, node, **_):
        try:
            if not node:
                QTimer.singleShot(0, self._clear_agent_data)
                return

            QTimer.singleShot(0, lambda: self._apply_agent_data(node))
        except Exception as e:
            emit_gui_exception_log("AgentDetailPanel.set_agent_data", e)


    def _clear_agent_data(self):

        try:
            self.thread_table.clearContents()
            self.thread_table.setRowCount(0)
            self.spawn_table.clearContents()
            self.spawn_table.setRowCount(0)
            self.config_text.clear()
        except Exception as e:
            emit_gui_exception_log("AgentDetailPanel._clear_agent_data", e)

    def _apply_agent_data(self, node):

        try:
            if self._closing:
                return

            meta = node.get("meta", {})
            config = node.get("config", {})
            self.current_uuid = meta.get("universal_id", "-")

            # THREADS
            threads = meta.get("threads", [])
            self.thread_table.setColumnCount(6)
            self.thread_table.setHorizontalHeaderLabels([
                "Thread", "Status", "Delta", "Timeout", "Sleep", "Wake Due"
            ])
            self.thread_table.setRowCount(len(threads) or 1)

            # THREADS
            threads = meta.get("threads", [])
            self.thread_table.setColumnCount(6)
            self.thread_table.setHorizontalHeaderLabels([
                "Thread", "Status", "Delta", "Timeout", "Sleep", "Wake Due"
            ])
            self.thread_table.setRowCount(len(threads) or 1)

            if threads:
                for row, t in enumerate(threads):
                    status = t.get("status", "-")
                    delta = t.get("delta", "-")

                    self.thread_table.setItem(row, 0, QTableWidgetItem(str(t.get("thread", "-"))))
                    self.thread_table.setItem(row, 1, QTableWidgetItem(status))
                    self.thread_table.setItem(row, 2, QTableWidgetItem(str(delta)))
                    self.thread_table.setItem(row, 3, QTableWidgetItem(str(t.get("timeout", "-"))))
                    self.thread_table.setItem(row, 4, QTableWidgetItem(str(t.get("sleep_for", "-"))))
                    self.thread_table.setItem(row, 5, QTableWidgetItem(str(t.get("wake_due", "-"))))

                    # Color by status
                    color = None
                    if status == "alive":
                        color = QColor("#3CB371")  # green
                    elif status == "sleeping":
                        color = QColor("#FFD700")  # yellow
                    elif status == "failed":
                        color = QColor("#FF6347")  # red

                    if color:
                        for col in range(6):
                            self.thread_table.item(row, col).setForeground(QBrush(color))
            else:
                item = QTableWidgetItem("—")
                item.setTextAlignment(Qt.AlignCenter)
                item.setForeground(QBrush(QColor("#888")))
                self.thread_table.setItem(0, 0, item)

            # === Append Summary Row ===
            meta_summary = meta.get("summary", {})
            if meta_summary:
                row = self.thread_table.rowCount()
                self.thread_table.insertRow(row)
                # Column 0 = label
                self.thread_table.setItem(row, 0, QTableWidgetItem("⟳ Summary"))
                # Column 1 = thread_count
                self.thread_table.setItem(
                    row, 1,
                    QTableWidgetItem(f"Threads={meta_summary.get('thread_count', '-')}")
                )
                # Column 2 = latest delta
                self.thread_table.setItem(
                    row, 2,
                    QTableWidgetItem(f"Latest Δ={round(meta_summary.get('latest_delta', 0), 1)}")
                )
                # Column 3 = last seen
                self.thread_table.setItem(
                    row, 3,
                    QTableWidgetItem(f"Last Seen={meta_summary.get('last_seen_any', '-')}")
                )
                # Column 4 = sleep_for (not really meaningful globally)
                self.thread_table.setItem(row, 4, QTableWidgetItem("-"))
                # Column 5 = error
                self.thread_table.setItem(
                    row, 5,
                    QTableWidgetItem(f"Err={meta_summary.get('error', '-')}")
                )

            # SPAWNS
            spawn_info = meta.get("spawn_info", [])
            self.spawn_table.setRowCount(len(spawn_info) or 1)
            if spawn_info:
                for row, entry in enumerate(spawn_info):
                    ts = entry.get("timestamp", "-")
                    note = entry.get("note", "")
                    self.spawn_table.setItem(row, 0, QTableWidgetItem(str(ts)))
                    self.spawn_table.setItem(row, 1, QTableWidgetItem(note))
            else:
                item = QTableWidgetItem("—")
                item.setTextAlignment(Qt.AlignCenter)
                item.setForeground(QBrush(QColor("#888")))
                self.spawn_table.setItem(0, 0, item)

            # CONFIG
            self.current_config = config or {}
            self._update_config_text()

            # LABEL
            self.label.setText(
                f"Agent: {meta.get('name', '-')}"
                f"  Universal ID: {meta.get('universal_id', '-')}"
                f"  Spawn Count: {meta.get('spawn', '-')}"
                f"  Flip-Tripping: {'YES' if meta.get('flipping', False) else 'NO'}"
            )

        except Exception as e:
            emit_gui_exception_log("AgentDetailPanel._update_status_label", e)