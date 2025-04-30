# MatrixSwarm GUI Template: Command Bridge Layout (PyQt5)

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTreeWidget, QTreeWidgetItem,
    QTextEdit, QComboBox, QLineEdit, QGroupBox, QSplitter, QFileDialog
)
from PyQt5.QtCore import Qt
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMessageBox

from PyQt5.QtWidgets import QListWidget, QListWidgetItem


import sys
from agent.core.live_tree import LiveTree
import os
import time
import json

#SWIPE OUT THE IP AND PORT FOR YOUR OWN
MATRIX_HOST = "https://147.135.68.135:65431/matrix"
AGENTS_HOST = "https://147.135.68.135:65431/agents"
CLIENT_CERT = ("certs/client.crt", "certs/client.key")
SERVER_CERT = "certs/server.crt"
REQUEST_TIMEOUT = 5

class MatrixCommandBridge(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MatrixSwarm V2: Command Bridge")
        self.setMinimumSize(1400, 800)

        layout = QHBoxLayout()
        self.setLayout(layout)

        # Panels
        self.left_panel = self.create_mission_panel()
        self.center_panel = self.create_tree_panel()
        self.right_panel = self.create_log_panel()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.center_panel)
        splitter.addWidget(self.right_panel)
        splitter.setSizes([300, 800, 300])

        self.center_panel = self.create_tree_panel()
        self.tree_display = QListWidget()
        self.tree_display.itemClicked.connect(self.handle_tree_click)

        self.conn_status = QLabel("🔴 Disconnected")
        self.conn_status.setStyleSheet("color: red; background-color: #252526; font-family: Courier;")

        layout.addWidget(self.conn_status)

        layout.addWidget(splitter)

        self.start_connection_monitor()


    def handle_tree_click(self, item):
        perm_id = item.data(Qt.UserRole)
        self.agent_log_entry.setText(perm_id)
        print(f"[CLICK] Clicked agent {perm_id}")

    def create_mission_panel(self):
        box = QGroupBox("🧩 Mission Console")
        layout = QVBoxLayout()

        self.agent_name = QLineEdit()
        self.agent_name.setPlaceholderText("agent_name")
        self.perm_id = QLineEdit()
        self.perm_id.setPlaceholderText("permanent_id")
        self.target_id = QLineEdit()
        self.target_id.setPlaceholderText("target_permanent_id")
        self.delegate = QLineEdit()
        self.delegate.setPlaceholderText("comma,separated,delegated")

        layout.addWidget(self.agent_name)
        layout.addWidget(self.perm_id)
        layout.addWidget(self.target_id)
        layout.addWidget(self.delegate)

        layout.addWidget(QPushButton("RESUME AGENT"))
        layout.addWidget(QPushButton("SHUTDOWN AGENT"))
        layout.addWidget(QPushButton("INJECT TO TREE"))
        layout.addWidget(QPushButton("CALL REAPER"))
        layout.addWidget(QPushButton("DELETE SUBTREE"))

        self.upload_btn = QPushButton("Upload Agent Code")
        self.upload_btn.clicked.connect(self.upload_agent_code)
        layout.addWidget(self.upload_btn)

        box.setLayout(layout)
        return box

    def create_tree_panel(self):
        box = QGroupBox("🧠 Hive Tree View")
        layout = QVBoxLayout()

        box = QGroupBox("🧠 Hive Tree View")
        layout = QVBoxLayout()

        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Hive Agents")

        reload_btn = QPushButton("Reload Tree")
        layout.addWidget(self.tree)
        layout.addWidget(reload_btn)

        self.download_stats = QLabel("⏳ Waiting for data...")
        self.download_stats.setStyleSheet("color: gray; background-color: #252526; font-family: Courier; padding: 5px;")
        self.download_stats.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.download_stats)

        return box

    def create_log_panel(self):
        box = QGroupBox("📡 Agent Intel & Logs")
        layout = QVBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_input = QLineEdit()
        self.log_input.setPlaceholderText("Enter agent perm_id to view logs")

        layout.addWidget(self.log_input)
        layout.addWidget(QPushButton("View Logs"))
        layout.addWidget(self.log_text)

        box.setLayout(layout)
        return box

    def upload_agent_code(self):
        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getOpenFileName(self, "Select Agent Python File", "", "Python Files (*.py)", options=options)
        if file_name:
            # Placeholder: Copy to a staging folder or trigger upload logic
            print(f"[UPLOAD] Selected agent source: {file_name}")
            # TODO: Notify Matrix if she requests agent and code is available

    def start_connection_monitor(self):
        self.conn_timer = QTimer(self)
        self.conn_timer.timeout.connect(self.check_matrix_connection)
        self.conn_timer.start(5000)  # every 5000 ms = 5 seconds

    def check_matrix_connection(self):
        import requests
        response = None  # ⚠️ Needed for safe handling outside try

        try:
            response = requests.get(
                url=MATRIX_HOST + "/ping",  # must be supported by Matrix
                cert=CLIENT_CERT,
                verify=False,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                self.conn_status.setText("🟢 Connected")
                self.conn_status.setStyleSheet("color: #00ff66;")
                return True

        except Exception as e:
            print(f"[ERROR][CONNECTION CHECK] {e}")

        self.conn_status.setText("🔴 Disconnected")
        self.conn_status.setStyleSheet("color: red;")

        # ✅ Only check response if it exists
        if response and response.status_code == 200:
            self.request_tree_from_matrix()

        return False

    def request_tree_from_matrix(self):
        import requests
        try:
            payload = {
                "type": "list_tree",
                "timestamp": time.time(),
                "content": {}
            }

            response = requests.post(
                url=MATRIX_HOST,
                json=payload,
                cert=CLIENT_CERT,
                verify=False,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 200:


                tree = response.json().get("tree", {})


                if not tree:
                    QMessageBox.critical(self, "Tree Load Error", "Matrix returned no tree data.")

                print("[DEBUG] Raw tree payload:\n", json.dumps(tree, indent=2))

                output = self.render_tree(tree.get("matrix", {}))

                self.tree_display.clear()
                header = QListWidgetItem(f"[MATRIX TREE @ {time.strftime('%H:%M:%S')}]")
                header.setForeground(Qt.gray)
                self.tree_display.addItem(header)

                for idx, (line, perm_id, color) in enumerate(output):
                    item = QListWidgetItem(line)
                    item.setData(Qt.UserRole, perm_id)

                    if color == "green":
                        item.setForeground(Qt.green)
                    elif color == "red":
                        item.setForeground(Qt.red)
                    else:
                        item.setForeground(Qt.white)

                    self.tree_display.addItem(item)

            else:
                QMessageBox.critical(self, "Matrix Error", f"{response.status_code}: {response.text}")

        except Exception as e:
            QMessageBox.critical(self, "Request Failed", str(e))



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
        if isinstance(children, list):
            if children:
                label += f" ({len(children)})"
        else:
            label += " [INVALID CHILD FORMAT]"
            children = []

        line = f"{indent}- {label}"
        output.append((line, perm_id, color))

        for child in children:
            output.extend(self.render_tree(child, indent + "  "))

        return output

    def start_tree_autorefresh(self, interval=10):
        def refresh():
            self.load_tree_from_matrix()
            self.after(interval * 1000, refresh)

        refresh()

    def load_tree(self):
        tree = LiveTree()
        output = []

        def recurse(node, indent=""):
            line = f"{indent}- {node}"
            if node.get("confirmed"):
                line += " ✓"
            output.append(line)
            for child in tree.get_delegates(node):
                recurse(child, indent + "  ")

        root_node = tree.nodes.get("matrix")  # ← Replace "matrix" with actual root perm_id if dynamic
        if root_node:
            recurse(root_node)
        else:
            output.append(("[ERROR] Root node 'matrix' not found.", "none"))

        self.tree_display.delete("1.0", tk.END)
        self.tree_display.insert(tk.END, f"[TREE SYNC @ {time.strftime('%H:%M:%S')}]\n\n")
        self.tree_display.insert(tk.END, "\n".join(output))

    # Usage in request_tree_from_matrix response
    def load_tree_from_matrix(self):
        try:
            import requests
            payload = {
                "type": "list_tree",
                "timestamp": time.time(),
                "content": {}
            }
            response = requests.post(
                url=MATRIX_HOST,
                json=payload, cert = ("certs/client.crt", "certs/client.key"),
                verify=False,  # ⚠️ DISABLES SSL VERIFICATION
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 200:
                tree = response.json().get("tree", {})
                lines = []

                # The root node is the entire tree object
                root_node = tree if isinstance(tree, dict) and "permanent_id" in tree else None
                if root_node:
                    lines = self.render_tree(root_node)
                else:
                    lines = [("[ERROR] Invalid or empty tree structure returned.", "none")]

                self.tree_display.delete("1.0", tk.END)
                self.tree_display.insert(tk.END, f"[MATRIX TREE @ {time.strftime('%H:%M:%S')}]\n\n")

                for idx, (line, perm_id) in enumerate(lines):
                    tag = f"perm_{idx}"
                    self.tree_display.insert(tk.END, line + "\n", tag)
                    if perm_id != "none":
                        # Inject it into the log input as well
                        self.agent_log_entry.delete(0, tk.END)
                        self.agent_log_entry.insert(0, perm_id)

                        self.tree_display.tag_bind(tag, "<Button-1>", self.make_click_callback(perm_id))

                        print(f"[CLICK-BIND] Clicked tag bound to perm_id: {perm_id}")
            else:
                messagebox.showerror("Matrix Error", f"{response.status_code}: {response.text}")

        except Exception as e:
            messagebox.showerror("Request Failed", str(e))

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MatrixCommandBridge()
    window.show()
    sys.exit(app.exec_())
