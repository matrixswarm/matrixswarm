from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem,
    QLineEdit, QGroupBox, QSplitter, QFileDialog,
    QTextEdit, QStatusBar, QSizePolicy, QStackedLayout
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QPalette
import sys
import requests
import os
import json
import time

MATRIX_HOST = "https://147.135.68.135:65431/matrix" #put your own ip here, not mine
CLIENT_CERT = ("certs/client.crt", "certs/client.key")  #certs go in the folder, on client and on server, read readme for instructions to generate
REQUEST_TIMEOUT = 5

class MatrixCommandBridge(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MatrixSwarm V2: Command Bridge")
        self.setMinimumSize(1400, 800)
        self.setup_ui()
        self.setup_status_bar()
        self.setup_timers()
        self.check_matrix_connection()

    def setup_ui(self):
        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)

        self.stack = QStackedLayout()
        self.command_view = self.build_command_view()
        self.code_view = self.build_code_view()

        self.stack.addWidget(self.command_view)
        self.stack.addWidget(self.code_view)

        self.main_layout.addLayout(self.stack)

    def setup_status_bar(self):
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("color: #33ff33; background-color: #111; font-family: Courier;")
        self.status_bar.setFixedHeight(30)
        self.status_label = QLabel("🔴 Disconnected")
        self.status_bar.addPermanentWidget(self.status_label)
        self.main_layout.addWidget(self.status_bar)

    def setup_timers(self):
        self.pulse_state = True
        self.pulse_timer = QTimer()
        self.pulse_timer.timeout.connect(self.toggle_status_dot)
        self.pulse_timer.start(1000)

        self.start_tree_autorefresh(interval=5)

    def toggle_status_dot(self):
        if self.status_label.text().endswith("Connected"):
            dot = "🟢" if self.pulse_state else "⚫"
            self.status_label.setText(f"{dot} Connected")
            self.pulse_state = not self.pulse_state

    def build_command_view(self):
        container = QWidget()
        layout = QHBoxLayout(container)

        self.left_panel = self.build_command_panel()
        self.center_panel = self.build_tree_panel()
        self.right_panel = self.build_log_panel()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.center_panel)
        splitter.addWidget(self.right_panel)
        splitter.setSizes([300, 800, 300])

        layout.addWidget(splitter)
        return container

    def build_code_view(self):
        container = QWidget()
        layout = QVBoxLayout()
        label = QLabel("[CODE VIEW] Future codex, code preview, or live injection shell will go here.")
        label.setStyleSheet("color: #33ff33; font-family: Courier; padding: 20px;")
        layout.addWidget(label)

        back_btn = QPushButton("⬅️ Return to Command View")
        back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        back_btn.setStyleSheet("background-color: #111; color: #33ff33; border: 1px solid #00ff66;")
        layout.addWidget(back_btn)

        container.setLayout(layout)
        return container

    def handle_tree_click(self, item):
        perm_id = item.data(Qt.UserRole)
        self.log_input.setText(perm_id)
        self.view_logs()

    def view_logs(self):
        perm_id = self.log_input.text().strip()
        payload = {
            "type": "get_log",
            "timestamp": time.time(),
            "content": {"perm_id": perm_id}
        }
        try:
            response = requests.post(
                url=MATRIX_HOST,
                json=payload,
                cert=CLIENT_CERT,
                verify=False,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                data = response.json()
                logs = data.get("log", "[NO LOG DATA RECEIVED]")
                self.log_text.setPlainText(logs)
                self.log_text.moveCursor(self.log_text.textCursor().End)
            else:
                try:
                    message = response.json().get("message", response.text)
                except Exception:
                    message = response.text
                self.log_text.setPlainText(f"[MATRIX ERROR] Could not retrieve logs for {perm_id}:{message}")
        except Exception as e:
            self.log_text.setPlainText(f"[ERROR] Failed to connect to Matrix:\n{str(e)}")

    def start_tree_autorefresh(self, interval=10):
        self.tree_timer = QTimer(self)
        self.tree_timer.timeout.connect(self.request_tree_from_matrix)
        self.tree_timer.start(interval * 1000)

    def request_tree_from_matrix(self):
        try:
            payload = {"type": "list_tree", "timestamp": time.time(), "content": {}}
            response = requests.post(
                url=MATRIX_HOST,
                json=payload,
                cert=CLIENT_CERT,
                verify=False,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                self.status_label.setText("🟢 Connected")
                tree = response.json().get("tree", {})
                self.render_tree_to_gui(tree)
            else:
                self.status_label.setText("🔴 Disconnected")
        except Exception:
            self.status_label.setText("🔴 Disconnected")

    def render_tree_to_gui(self, tree):
        output = self.render_tree(tree)
        self.tree_display.clear()
        header = QListWidgetItem(f"[MATRIX TREE @ {time.strftime('%H:%M:%S')}]")
        header.setForeground(QColor("#888"))
        self.tree_display.addItem(header)
        for line, perm_id, color in output:
            item = QListWidgetItem(line)
            item.setData(Qt.UserRole, perm_id)
            item.setForeground(QColor("#33ff33") if color == "green" else QColor("#ff5555") if color == "red" else QColor("#33ff33"))
            self.tree_display.addItem(item)

    def render_tree(self, node, indent=""):
        output = []
        if not isinstance(node, dict):
            output.append((f"{indent}- [INVALID NODE STRUCTURE: {node}]", "none", "red"))
            return output

        perm_id = node.get("permanent_id") or node.get("name") or "unknown"
        label = perm_id
        color = "white"

        die_path = os.path.join("comm", perm_id, "incoming", "die")
        if os.path.exists(die_path):
            label += " ⚠️ [DOWN]"
            color = "red"

        if node.get("confirmed"):
            label += " ✓"
            color = "green"

        children = node.get("children", [])
        if isinstance(children, list) and children:
            label += f" ({len(children)})"

        line = f"{indent}- {label}"
        output.append((line, perm_id, color))
        for child in children:
            output.extend(self.render_tree(child, indent + "  "))
        return output


    def upload_agent_code(self):
        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Agent Python File", "", "Python Files (*.py)", options=options)
        if file_name:
            print(f"[UPLOAD] Selected agent source: {file_name}")

    def build_command_panel(self):
        box = QGroupBox("🧩 Mission Console")
        layout = QVBoxLayout()
        layout.setSpacing(6)

        self.agent_name = QLineEdit("agent_name")
        self.perm_id = QLineEdit("permanent_id")
        self.target_id = QLineEdit("target_permanent_id")
        self.delegate = QLineEdit("comma,separated,delegated")

        for widget in [self.agent_name, self.perm_id, self.target_id, self.delegate]:
            widget.setStyleSheet("background-color: #000; color: #33ff33; border: 1px solid #00ff66;")
            layout.addWidget(widget)

        for label in ["RESUME AGENT", "SHUTDOWN AGENT", "INJECT TO TREE", "CALL REAPER", "DELETE SUBTREE"]:
            btn = QPushButton(label)
            btn.setStyleSheet("background-color: #1e1e1e; color: #33ff33; border: 1px solid #00ff66;")
            layout.addWidget(btn)

        self.upload_btn = QPushButton("Upload Agent Code")
        self.upload_btn.clicked.connect(self.upload_agent_code)
        self.upload_btn.setStyleSheet("background-color: #1e1e1e; color: #33ff33; border: 1px solid #00ff66;")
        layout.addWidget(self.upload_btn)

        toggle_btn = QPushButton("🧠 Switch to Code View")
        toggle_btn.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        toggle_btn.setStyleSheet("background-color: #000; color: #00ff66; font-weight: bold;")
        layout.addWidget(toggle_btn)

        box.setLayout(layout)
        return box

    def check_matrix_connection(self):
        try:
            response = requests.get(
                url=MATRIX_HOST + "/ping",
                cert=CLIENT_CERT,
                verify=False,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                self.status_label.setText("🟢 Connected")
            else:
                self.status_label.setText("🔴 Disconnected")
        except Exception:
            self.status_label.setText("🔴 Disconnected")


    def build_tree_panel(self):
        box = QGroupBox("🧠 Hive Tree View")
        layout = QVBoxLayout()

        self.tree_display = QListWidget()
        self.tree_display.itemClicked.connect(self.handle_tree_click)
        self.tree_display.setStyleSheet("""
            QListWidget {
                background-color: #000000;
                color: #33ff33;
                font-family: Courier;
                font-size: 14px;
                padding: 5px;
                border: 1px solid #00ff66;
            }
            QListWidget::item {
                padding: 4px;
            }
            QListWidget::item:selected {
                background-color: #00ff66;
                color: #000000;
            }
        """)

        reload_btn = QPushButton("Reload Tree")
        reload_btn.clicked.connect(self.request_tree_from_matrix)
        reload_btn.setStyleSheet("background-color: #111; color: #33ff33; border: 1px solid #00ff66;")

        layout.addWidget(self.tree_display)
        layout.addWidget(reload_btn)
        box.setLayout(layout)
        return box


    def build_log_panel(self):
        box = QGroupBox("📡 Agent Intel Logs")
        layout = QVBoxLayout()

        self.log_input = QLineEdit()
        self.log_input.setPlaceholderText("Enter agent perm_id to view logs")
        self.log_input.setStyleSheet("background-color: #000; color: #33ff33; border: 1px solid #00ff66;")

        view_btn = QPushButton("View Logs")
        view_btn.clicked.connect(self.view_logs)
        view_btn.setStyleSheet("background-color: #111; color: #33ff33; border: 1px solid #00ff66;")

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(300)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #000;
                color: #33ff33;
                font-family: Courier;
                font-size: 13px;
                padding: 10px;
                border: 1px solid #00ff66;
            }
        """)

        layout.addWidget(self.log_input)
        layout.addWidget(view_btn)
        layout.addWidget(self.log_text)
        box.setLayout(layout)
        return box

if __name__ == '__main__':
    app = QApplication(sys.argv)

    dark_palette = app.palette()
    dark_palette.setColor(app.palette().Window, QColor("#121212"))
    dark_palette.setColor(app.palette().Base, QColor("#000000"))
    dark_palette.setColor(app.palette().AlternateBase, QColor("#1e1e1e"))
    dark_palette.setColor(app.palette().Button, QColor("#1a1a1a"))
    dark_palette.setColor(app.palette().ButtonText, QColor("#33ff33"))
    dark_palette.setColor(app.palette().Text, QColor("#33ff33"))
    dark_palette.setColor(app.palette().BrightText, QColor("#33ff33"))
    dark_palette.setColor(app.palette().WindowText, QColor("#33ff33"))
    app.setPalette(dark_palette)
    app.setStyleSheet("""
                QWidget {
                    background-color: #121212;
                    color: #33ff33;
                    font-family: Courier;
                }
                QLineEdit, QTextEdit, QListWidget, QPushButton {
                    background-color: #000;
                    color: #33ff33;
                    border: 1px solid #00ff66;
                }
                QGroupBox {
                    color: #33ff33;
                    border: 1px solid #00ff66;
                    margin-top: 1ex;
                    font-weight: bold;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    subcontrol-position: top center;
                    padding: 0 3px;
                    color: #33ff33;
                }
                QPushButton:hover {
                    background-color: #1e1e1e;
                }
            """)

    window = MatrixCommandBridge()
    window.show()
    sys.exit(app.exec_())
