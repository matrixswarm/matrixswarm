from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem,
    QLineEdit, QGroupBox, QSplitter, QFileDialog,
    QTextEdit, QStatusBar, QSizePolicy, QStackedLayout, QCheckBox, QComboBox
)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QPalette
import sys
import requests
import os
import json
import time
import base64
import hashlib
import string
import random
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
        self.hotswap_btn.setEnabled(False)

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

        self.start_tree_autorefresh(interval=25)

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
        self.codex_display = QTextEdit()
        self.codex_display.setReadOnly(True)
        self.codex_display.setStyleSheet("background-color: #000; color: #00ffcc; font-family: Courier;")
        layout.addWidget(self.codex_display)

        self.load_codex_entries()
        label.setStyleSheet("color: #33ff33; font-family: Courier; padding: 20px;")
        layout.addWidget(label)


        back_btn = QPushButton("⬅️ Return to Command View")
        back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        back_btn.setStyleSheet("background-color: #111; color: #33ff33; border: 1px solid #00ff66;")
        layout.addWidget(back_btn)

        self.loading_frames = ["⏳", "🔁", "⌛"]
        self.loading_index = 0

        self.loading_timer = QTimer()
        self.loading_timer.timeout.connect(self.animate_loader)
        self.loading_timer.start(300)

        container.setLayout(layout)
        return container

    def animate_loader(self):
        if hasattr(self, "tree_loading_label") and self.tree_stack.currentIndex() == 0:
            icon = self.loading_frames[self.loading_index % len(self.loading_frames)]
            self.tree_loading_label.setText(f"{icon} Loading agent tree from Matrix...")
            self.loading_index += 1

    def handle_tree_click(self, item):
        try:
            print("[CLICK] Triggered")

            universal_id = item.data(Qt.UserRole)
            if not universal_id:
                print("[CLICK] No universal_id from UserRole")
                return

            node = self.agent_tree_flat.get(universal_id)
            if not node:
                print(f"[TREE-CLICK] No node found for universal_id: {universal_id}")
                return

            universal_id = item.data(Qt.UserRole)
            self.input_universal_id.setText(universal_id)
            self.hotswap_btn.setEnabled(True)
            if hasattr(self, "log_panel"):
                self.log_panel.append(f"[GUI] Selected agent: {universal_id}")

            info_lines = [
                f"🧠 Name: {node.get('name', '')}",
                f"🆔 Perm ID: {universal_id}",
                f"👥 Delegates: {', '.join(node.get('delegated', [])) or 'None'}",
                f"📁 Filesystem: {json.dumps(node.get('filesystem', {}), indent=2)}",
                f"⚙️ Config: {json.dumps(node.get('config', {}), indent=2)}"
            ]

            if node.get("confirmed"):
                info_lines.append("✅ Status: ALIVE")
            else:
                info_lines.append("⚠️ Status: UNCONFIRMED / DOWN")

            self.agent_info_panel.setText("\n".join(info_lines))
            print("[CLICK] Update complete")

            self.log_input.setText(universal_id)
            self.view_logs()



        except Exception as e:
            print(f"[TREE-CLICK][CRASH] {e}")
            self.agent_info_panel.setText("⚠️ Failed to load agent info.")


    def send_payload_to_matrix(self, success_message="Payload delivered."):

        payload_text = self.payload_editor.toPlainText().strip()
        if not payload_text:
            self.status_label.setText("⚠️ No payload to send.")
            return

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as e:
            self.status_label.setText(f"⚠️ Invalid JSON: {e}")
            return

        # Inject selected universal_id as target if not already set
        target = self.input_universal_id.text().strip()
        if target:
            payload.setdefault("target", target)
            payload.setdefault("content", {})
            payload["content"].setdefault("universal_id", target)
            #folder to deliever to
            folder = self.folder_selector.currentText()
            payload["content"]["delivery"] = folder
        try:
            response = requests.post(
                url=MATRIX_HOST,
                json=payload,
                cert=CLIENT_CERT,
                verify=False,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                try:
                    message = response.json().get("message", success_message)
                except Exception:
                    message = success_message
                self.status_label.setText(f"✅ {message}")

            else:
                self.status_label.setText(f"❌ Matrix responded: {response.status_code}")
        except Exception as e:
            self.status_label.setText(f"❌ Failed to send payload: {e}")

    def handle_alarm_message(self, msg):
        alarm = json.loads(msg)
        print(f"🔥 ALARM RECEIVED: {alarm}")
        self.status_label.setText(f"🚨 {alarm.get('universal_id')} ALERT: {alarm.get('cause')}")

    def view_logs(self):
        universal_id = self.log_input.text().strip().split(" ")[0]

        payload = {
            "type": "get_log",
            "timestamp": time.time(),
            "content": {"universal_id": universal_id}
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
                if self.auto_scroll_checkbox.isChecked():
                    self.log_text.moveCursor(self.log_text.textCursor().End)
            else:
                try:
                    message = response.json().get("message", response.text)
                except Exception:
                    message = response.text
                self.log_text.setPlainText(f"[MATRIX ERROR] Could not retrieve logs for {universal_id}:{message}")
        except Exception as e:
            self.log_text.setPlainText(f"[ERROR] Failed to connect to Matrix:\n{str(e)}")

    def start_tree_autorefresh(self, interval=10):
        self.tree_timer = QTimer(self)
        self.tree_timer.timeout.connect(self.request_tree_from_matrix)
        self.tree_timer.start(interval * 1000)

    def request_tree_from_matrix(self):

        self.tree_stack.setCurrentIndex(0)  # Show loading
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

        self.tree_stack.setCurrentIndex(1)  # Show tree

    def render_tree_to_gui(self, tree):
        output = self.render_tree(tree)
        self.tree_display.clear()
        # Flat universal_id lookup for handle_tree_click
        self.agent_tree_flat = {}

        def recurse_flatten(node):
            if not isinstance(node, dict):
                return
            if "universal_id" in node:
                self.agent_tree_flat[node["universal_id"]] = node
            for child in node.get("children", []):
                recurse_flatten(child)

        recurse_flatten(tree)

        header = QListWidgetItem(f"[MATRIX TREE @ {time.strftime('%H:%M:%S')}]")
        header.setForeground(QColor("#888"))
        self.tree_display.addItem(header)
        for line, universal_id, color in output:
            item = QListWidgetItem(line)
            item.setData(Qt.UserRole, universal_id)
            item.setForeground(QColor("#33ff33") if color == "green" else QColor("#ff5555") if color == "red" else QColor("#33ff33"))
            self.tree_display.addItem(item)

        if universal_id == self.input_universal_id.text().strip():
            self.tree_display.setCurrentItem(item)
            self.tree_display.scrollToItem(item)

    def render_tree(self, node, indent="", is_last=True):
        output = []
        if not isinstance(node, dict):
            output.append((f"{indent}└─ [INVALID NODE STRUCTURE: {node}]", "none", "red"))
            return output

        universal_id = node.get("universal_id") or node.get("name") or "unknown"
        agent_type = (node.get("name") or node.get("universal_id", "")).split("-")[0].lower()
        icon_map = {
            "matrix": "🧠", "reaper": "💀", "scavenger": "🧹", "sentinel": "🛡️",
            "oracle": "🔮", "mailman": "📬", "logger": "❓", "worker": "🧍",
            "metrics": "📊", "calendar": "📅", "uptime_pinger": "📡",
            "filewatch": "📁", "codex_tracker": "📜", "reactor": "⚡",
            "sweeper": "🧭", "discord": "📣", "telegram": "🛰️", "mirror": "❓",
            "commander": "🧱"
        }
        icon = icon_map.get(agent_type, "📄")
        color = "white"

        if agent_type not in icon_map:
            icon = "❓"

        die_path = os.path.join("comm", universal_id, "incoming", "die")
        if os.path.exists(die_path):
            universal_id += " ⚠️ [DOWN]"
            color = "red"

        if node.get("confirmed"):
            color = "green"

        children = node.get("children", [])
        display_id = universal_id  # keep raw ID untouched
        if isinstance(children, list) and children:
            display_id += f" ({len(children)})"

        prefix = "└─ " if is_last else "├─ "
        line = f"{indent}{prefix}{icon} {display_id}"
        output.append((line, universal_id, color))

        for i, child in enumerate(children):
            last = (i == len(children) - 1)
            child_indent = indent + ("   " if is_last else "│  ")
            output.extend(self.render_tree(child, child_indent, is_last=last))

        return output

    def random_suffix(self,length=5):
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

    def hotswap_agent_code(self):
        import importlib.util
        import base64
        import hashlib
        import os

        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select Agent Python File",
            "",
            "Python Files (*.py)",
            options=options
        )

        if not file_name:
            return

        try:
            # Load .py source and hash
            with open(file_name, "rb") as f:
                code = f.read()
                encoded = base64.b64encode(code).decode("utf-8")
                file_hash = hashlib.sha256(code).hexdigest()


            # Grab current universal_id from GUI
            target_uid = self.input_universal_id.text().strip()

            # Try to get base name from the tree
            base_name = self.agent_tree_flat.get(target_uid, {}).get("name")

            # Fallback to filename if no tree mapping
            if not base_name:
                base_name = os.path.basename(file_name).replace(".py", "")

            suffix = self.random_suffix(5)

            # Generate randomized hot swap ID
            suffix = self.random_suffix(5)
            randomized_name = f"{base_name}_bp_{suffix}"

            # 🔍 Load optional deploy_directive.py
            source_dir = os.path.dirname(file_name)
            directive_path = os.path.join(source_dir, "deploy_directive.py")

            if os.path.exists(directive_path):
                spec = importlib.util.spec_from_file_location("deploy_directive", directive_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                deploy_data = module.directive
            else:
                deploy_data = {}

            # 🔒 Enforce all required fields and fallback structure
            deploy_data["name"] = randomized_name
            deploy_data.setdefault("app", "matrix-core")
            deploy_data.setdefault("hotswap", True)
            deploy_data.setdefault("config", {})
            deploy_data.setdefault("filesystem", {})
            deploy_data.setdefault("directives", {})

            # ⚡ Universal ID: GUI input or fallback to randomized
            universal_id = self.input_universal_id.text().strip() or randomized_name
            deploy_data["universal_id"] = target_uid

            # 🧠 Inject encoded source and SHA256
            deploy_data["source_payload"] = {
                "payload": encoded,
                "sha256": file_hash
            }

            # 🎯 Final payload
            payload = {
                "type": "replace_agent",
                "timestamp": time.time(),
                "content": {
                    "target_universal_id": universal_id,
                    "new_agent": deploy_data,
                    "hotswap": True
                }
            }

            print("🧠 FINAL new_agent:", json.dumps(deploy_data, indent=2))

            # ✅ Launch
            self.send_post_to_matrix(payload, f"🔥 Hotswap deployed for {universal_id} [{file_hash[:8]}...]")

        except Exception as e:
            self.status_label.setText(f"❌ Hotswap failed: {e}")

    def build_command_panel(self):
        box = QGroupBox("🧩 Mission Console")
        layout = QVBoxLayout()
        layout.setSpacing(6)

        self.input_agent_name = QLineEdit("agent_name")
        self.input_universal_id = QLineEdit("universal_id")
        self.input_target_universal_id = QLineEdit("target_universal_id")
        self.input_delegated = QLineEdit("comma,separated,delegated")

        for widget in [self.input_agent_name, self.input_universal_id, self.input_target_universal_id, self.input_delegated]:
            widget.setStyleSheet("background-color: #000; color: #33ff33; border: 1px solid #00ff66;")
            layout.addWidget(widget)


        #self.upload_btn = QPushButton("Upload Agent Code")
        #self.upload_btn.clicked.connect(self.upload_agent_code)

        self.hotswap_btn = QPushButton("🔥 Hotswap")
        self.hotswap_btn.clicked.connect(self.hotswap_agent_code)
        self.hotswap_btn.setToolTip("Replace the agent's logic with a live hot-swapped source file.")
        self.hotswap_btn.setStyleSheet("background-color: #1e1e1e; color: #ff4444; border: 1px solid #00ff66;")
        self.hotswap_btn.setEnabled(False)
        layout.addWidget(self.hotswap_btn)

        self.folder_selector = QComboBox()
        self.folder_selector.addItems(["payload", "incoming", "queue", "stack", "replies", "broadcast"])
        self.folder_selector.setStyleSheet("background-color: black; color: #00ffcc; font-family: Courier;")
        layout.addWidget(QLabel("📁 Send to folder:"))
        layout.addWidget(self.folder_selector)

        self.payload_editor = QTextEdit()
        self.payload_editor.setPlaceholderText("Enter JSON payload to send to agent over the wire...")
        self.payload_editor.setStyleSheet("background-color: #000; color: #00ffcc; font-family: Courier;")
        self.payload_editor.setFixedHeight(150)
        layout.addWidget(self.payload_editor)

        send_payload_btn = QPushButton("🚀 SEND PAYLOAD TO AGENT")
        send_payload_btn.clicked.connect(self.send_payload_to_matrix)
        send_payload_btn.setStyleSheet(
            "background-color: #111; color: #00ffcc; border: 1px solid #00ff66; font-weight: bold;")
        layout.addWidget(send_payload_btn)

        reboot_btn = QPushButton("💥 HARD BOOT SYSTEM")
        reboot_btn.clicked.connect(self.send_reboot_agent)
        layout.addWidget(reboot_btn)

        toggle_btn = QPushButton("🧠 Switch to Code View")
        toggle_btn.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        toggle_btn.setStyleSheet("background-color: #000; color: #00ff66; font-weight: bold;")
        layout.addWidget(toggle_btn)

        box.setLayout(layout)
        return box

    def send_reboot_agent(self):

        from PyQt5.QtWidgets import QMessageBox

        confirm = QMessageBox.question(self, "Confirm Reboot",
                                       "⚠️ This will trigger a hard system reboot via bootloader.\nProceed?",
                                       QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return

        payload = {
            "type": "spawn_agent",
            "timestamp": time.time(),
            "content": {
                "agent_name": "reboot_agent",
                "universal_id": "reboot-1",
                "filesystem": {},
                "config": {
                    "confirm": "YES",  # ✅ REQUIRED
                    "shutdown_all": True,
                    "reboot_matrix": True
                }
            }
        }

        requests.post(
            url=MATRIX_HOST,
            json=payload,
            cert=CLIENT_CERT,
            verify=False,
            timeout=REQUEST_TIMEOUT
        )

    def handle_delete_agent(self):
        from PyQt5.QtWidgets import QMessageBox

        universal_id = self.input_universal_id.text().strip()
        if not universal_id:
            self.status_label.setText("⚠️ No agent selected.")
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"⚠️ This will erase the agent’s Codex record,\nkill its pod, and remove it from the tree.\n\nPermanently delete {universal_id}?",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm != QMessageBox.Yes:
            self.status_label.setText("🛑 Deletion canceled.")
            return

        payload = {
            "type": "delete_agent",
            "timestamp": time.time(),
            "content": {
                "target_universal_id": universal_id
            }
        }
        print(payload)
        self.send_post_to_matrix(payload, f"🗑 Deleted {universal_id}")

    def load_codex_entries(self):
        codex_dir = "/comm/matrix/codex/agents"
        if not os.path.exists(codex_dir):
            self.codex_display.setPlainText("[CODEX] No entries found.")
            return

        entries = []
        for file in os.listdir(codex_dir):
            try:
                with open(os.path.join(codex_dir, file)) as f:
                    data = json.load(f)
                    entry = f"🧬 {data.get('universal_id', '???')} – {data.get('title', 'Untitled')}\n{data.get('summary', '')}"
                    entries.append(entry)
            except Exception as e:
                entries.append(f"[ERROR] Failed to load {file}: {e}")

        self.codex_display.setPlainText("\n\n".join(entries) if entries else "[CODEX] Empty.")

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

        # Tree loading label
        self.tree_loading_label = QLabel("⏳ Loading agent tree from Matrix...")
        self.tree_loading_label.setAlignment(Qt.AlignCenter)
        self.tree_loading_label.setStyleSheet("color: #888; font-size: 16px; font-weight: bold;")
        self.tree_loading_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Tree list
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

        # Stack view for toggling between loading and tree
        self.tree_stack = QStackedLayout()
        self.tree_stack.addWidget(self.tree_loading_label)  # index 0
        self.tree_stack.addWidget(self.tree_display)  # index 1

        self.agent_info_panel = QLabel("[ Select an agent from the tree to view details ]")
        action_layout = QHBoxLayout()
        self.resume_btn = QPushButton("RESUME")
        self.shutdown_btn = QPushButton("SHUTDOWN")
        self.inject_btn = QPushButton("INJECT")
        self.reaper_btn = QPushButton("REAPER")
        self.delete_btn = QPushButton("DELETE")

        for btn in [self.resume_btn, self.shutdown_btn, self.inject_btn, self.reaper_btn, self.delete_btn]:
            btn.setStyleSheet("background-color: #1e1e1e; color: #33ff33; border: 1px solid #00ff66;")
            action_layout.addWidget(btn)

        layout.addLayout(action_layout)
        self.agent_info_panel.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.agent_info_panel.setStyleSheet("""
            QLabel {
                color: #33ff33;
                font-family: Courier;
                font-size: 13px;
                padding: 10px;
                border: 1px solid #00ff66;
            }
        """)
        layout.addWidget(self.agent_info_panel)

        # Button
        reload_btn = QPushButton("Reload Tree")
        reload_btn.clicked.connect(self.request_tree_from_matrix)
        reload_btn.setStyleSheet("background-color: #111; color: #33ff33; border: 1px solid #00ff66;")

        self.resume_btn.clicked.connect(self.handle_resume_agent)
        self.shutdown_btn.clicked.connect(self.handle_shutdown_agent)
        self.inject_btn.clicked.connect(self.handle_inject_to_tree)
        self.reaper_btn.clicked.connect(self.handle_call_reaper)
        self.delete_btn.clicked.connect(self.handle_delete_agent)


        layout.addLayout(self.tree_stack)
        layout.addWidget(reload_btn)
        box.setLayout(layout)
        return box

    def build_log_panel(self):
        box = QGroupBox("📡 Agent Intel Logs")
        layout = QVBoxLayout()

        self.log_input = QLineEdit()
        self.log_input.setPlaceholderText("Enter agent universal_id to view logs")
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

        self.auto_scroll_checkbox = QCheckBox("Auto-scroll logs")
        self.auto_scroll_checkbox.setChecked(True)
        self.auto_scroll_checkbox.setStyleSheet("color: #33ff33; font-family: Courier;")
        layout.addWidget(self.auto_scroll_checkbox)


        layout.addWidget(self.log_input)
        layout.addWidget(view_btn)
        layout.addWidget(self.log_text)
        box.setLayout(layout)
        return box

    def handle_resume_agent(self):
        universal_id = self.input_universal_id.text().strip()
        if not universal_id:
            self.status_label.setText("⚠️ No agent selected.")
            return

        payload = {
            "type": "resume",
            "timestamp": time.time(),
            "content": {
                "targets": [universal_id]
            }
        }

        self.send_post_to_matrix(payload, f"Resume sent to {universal_id}")

    def handle_shutdown_agent(self):
        universal_id = self.input_universal_id.text().strip()
        if not universal_id:
            self.status_label.setText("⚠️ No agent selected.")
            return

        payload = {
            "type": "stop",
            "timestamp": time.time(),
            "content": {
                "targets": [universal_id]
            }
        }

        self.send_post_to_matrix(payload, f"Shutdown signal sent to {universal_id}")

    def handle_inject_to_tree(self):
        target = self.input_target_universal_id.text().strip()
        universal_id = self.input_universal_id.text().strip()
        agent_name = self.input_agent_name.text().strip()
        delegated = [x.strip() for x in self.input_delegated.text().split(",") if x.strip()]

        if not target or not universal_id or not agent_name:
            self.status_label.setText("⚠️ Missing fields.")
            return

        payload = {
            "type": "inject",
            "timestamp": time.time(),
            "content": {
                "target_universal_id": target,
                "universal_id": universal_id,
                "agent_name": agent_name,
                "delegated": delegated
            }
        }

        self.send_post_to_matrix(payload, f"Injected {agent_name} under {target}")

    def handle_call_reaper(self):
        universal_id = self.input_universal_id.text().strip()
        if not universal_id:
            self.status_label.setText("⚠️ No agent selected.")
            return

        payload = {
            "type": "kill",
            "timestamp": time.time(),
            "content": {
                "targets": [universal_id]
            }
        }

        self.send_post_to_matrix(payload, f"Reaper dispatched for {universal_id}")

    def handle_delete_subtree(self):
        universal_id = self.input_universal_id.text().strip()
        if not universal_id:
            self.status_label.setText("⚠️ No agent selected.")
            return

        payload = {
            "type": "delete_subtree",
            "timestamp": time.time(),
            "content": {
                "universal_id": universal_id
            }
        }

        self.send_post_to_matrix(payload, f"Subtree delete issued for {universal_id}")

    def send_post_to_matrix(self, payload, success_message):
        try:
            response = requests.post(
                url=MATRIX_HOST,
                json=payload,
                cert=CLIENT_CERT,
                verify=False,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                self.status_label.setText(f"✅ {success_message}")
            else:
                self.status_label.setText(f"❌ Matrix error: {response.status_code}")
        except Exception as e:
            self.status_label.setText(f"❌ Connection failed: {e}")

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
