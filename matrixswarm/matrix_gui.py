from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem,
    QLineEdit, QGroupBox, QSplitter, QFileDialog,
    QTextEdit, QStatusBar, QSizePolicy, QStackedLayout, QCheckBox, QComboBox
)
from PyQt5.QtWidgets import QDesktopWidget
from PyQt5.QtWidgets import QMessageBox
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtMultimedia import QSound
import sys
import requests
import time
import string
import random
import ssl
import hashlib
import base64
import threading
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QListWidget
import os
import json

from matrixswarm.core.class_lib.packet_delivery.mixin.packet_factory_mixin import PacketFactoryMixin

SETTINGS_PATH = os.path.join("matrix_gui/config/settings.json")
def load_last_host():
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r") as f:
                data = json.load(f)
            return data.get("matrix_host", None)
    except Exception as e:
        print(f"[SETTINGS][ERROR] {e}")
    return None

def save_last_host(host):
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w") as f:
            json.dump({"matrix_host": host}, f)
    except Exception as e:
        print(f"[SETTINGS][SAVE ERROR] {e}")

class AutoScrollList(QListWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.autoscroll_enabled = True

    def enterEvent(self, event):
        self.autoscroll_enabled = False
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.autoscroll_enabled = True
        super().leaveEvent(event)


def run_in_thread(callback=None, error_callback=None):
    def decorator(func):
        def wrapper(*args, **kwargs):
            def thread_target():
                try:
                    result = func(*args, **kwargs)
                    if callback:
                        QTimer.singleShot(0, lambda r=result: callback(r))  # ✅ this captures the result properly
                except Exception as e:
                    print(f"[THREAD][ERROR] {e}")
                    if error_callback:
                        QTimer.singleShot(0, lambda: error_callback(e))
            threading.Thread(target=thread_target, daemon=True).start()
        return wrapper
    return decorator

#MATRIX_HOST = "https://147.135.68.135:65431/matrix" #put your own ip here, not mine
CLIENT_CERT = ("https_certs/client.crt", "https_certs/client.key")  #certs go in the folder, on client and on server, read readme for instructions to generate
REQUEST_TIMEOUT = 5


import asyncio
import websockets
from matrix_gui.crypto_alert_panel import CryptoAlertPanel

#when tree click event
class NodeSelectionEventBus(QObject):
    node_selected = pyqtSignal(str)
node_event_bus = NodeSelectionEventBus()


class MatrixCommandBridge(QWidget, PacketFactoryMixin):

    message_received = pyqtSignal(str)
    log_ready = pyqtSignal(dict, str)
    def __init__(self):
        super().__init__()
        self.matrix_host = load_last_host() or "https://147.135.112.25:65431/matrix"
        ws_ip = self.matrix_host.split("//")[1].split(":")[0]
        self.matrix_ws_host = f"wss://{ws_ip}:8765"
        self.setWindowTitle("MatrixSwarm V2: Command Bridge")
        self.setMinimumSize(1400, 800)
        self.setup_ui()
        self.setup_status_bar()
        self.setup_timers()
        self.check_matrix_connection()
        self.hotswap_btn.setEnabled(False)
        node_event_bus.node_selected.connect(self.forward_to_health_probe)
        self.message_received.connect(self.handle_websocket_message_safe)
        self.start_websocket_listener(self.matrix_ws_host)
        self.user_requested_log_view = False
        self.current_selected_uid =None
        self.last_probe_report = {}

        self.log_ready.connect(self._handle_logs_result)

        self.resize(1400, 800)  # or whatever size fits your battle station

        qr = self.frameGeometry()
        cp = QDesktopWidget().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

        self.log_scroll_timer = QTimer()
        self.log_scroll_timer.timeout.connect(self.slow_scroll_log)
        self.log_scroll_timer.start(100)  # Scroll every 100ms (adjust as needed)

        for alert in self.alert_panel.alerts:
            self.alert_panel.send_agent_payload(alert, partial=False)

    def change_matrix_host(self):
        host = self.host_input.text().strip()
        if not host.startswith("http"):
            self.status_label.setText("⚠️ Invalid host URL.")
            return
        self.matrix_host = host
        ws_ip = host.split("//")[1].split(":")[0]
        self.matrix_ws_host = f"wss://{ws_ip}:8765"
        save_last_host(host)
        self.status_label.setText(f"✅ Matrix host set to {host}. Reconnecting...")

    def slow_scroll_log(self):
        if self.auto_scroll_checkbox.isChecked() and self.log_text.isVisible():
            scrollbar = self.log_text.verticalScrollBar()
            max_scroll = scrollbar.maximum()
            current = scrollbar.value()

            if current < max_scroll:
                scrollbar.setValue(current + 1)

    def setup_ui(self):
        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)

        self.stack = QStackedLayout()
        self.command_view = self.build_command_view()
        self.code_view = self.build_code_view()

        self.stack.addWidget(self.command_view)
        self.stack.addWidget(self.code_view)

        self.main_layout.addLayout(self.stack)

        self.alert_panel = CryptoAlertPanel(
            alert_path=os.path.join("matrix_gui/config/alerts.json"),
            back_callback=self.show_main_panel
        )


        self.stack.addWidget(self.alert_panel)

    def show_main_panel(self):
        self.stack.setCurrentWidget(self.command_view)

    def setup_status_bar(self):
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("color: #33ff33; background-color: #111; font-family: Courier;")
        self.status_bar.setFixedHeight(30)
        self.status_label_matrix = QLabel("🔴 Matrix: Disconnected")
        self.status_label = QLabel("")  # For user feedback messages
        self.status_bar.addPermanentWidget(self.status_label)
        self.status_label_ws = QLabel("🔴 WS: Disconnected")
        self.status_bar.addPermanentWidget(self.status_label_matrix)
        self.status_bar.addPermanentWidget(self.status_label_ws)
        self.main_layout.addWidget(self.status_bar)

    def setup_timers(self):
        self.pulse_state = True
        self.pulse_timer = QTimer()
        self.pulse_timer.timeout.connect(self.toggle_status_dot)
        self.pulse_timer.start(1000)

        self.start_tree_autorefresh(interval=25)
        self.log_poll_timer = QTimer()
        self.log_poll_timer.timeout.connect(self.poll_live_log)
        self.log_poll_timer.start(2000)  # Poll every 2 seconds (adjust as needed)

    def poll_live_log(self):
        if self.auto_scroll_checkbox.isChecked():
            uid = self.log_input.text().strip()

            if hasattr(self, "_log_poll_busy") and self._log_poll_busy:
                return

            self._log_poll_busy = True

            if uid:
                self.view_logs()  # safely handles async fetch and appending

    def start_websocket_listener(self, url):
        def run_ws_loop():
            while True:
                try:
                    asyncio.set_event_loop(asyncio.new_event_loop())
                    loop = asyncio.get_event_loop()
                    loop.run_until_complete(self.websocket_main_loop(url))
                except Exception as e:
                    print(f"[WS][RETRY] Reconnect in 5s: {e}")
                time.sleep(5)  # Retry delay

        threading.Thread(target=run_ws_loop, daemon=True).start()

    async def websocket_main_loop(self, url):
        """
        Main asynchronous WebSocket loop.
        """
        try:
            print(f"[WS] Connecting to: {url}")

            ssl_context = None
            if url.startswith("wss://"):
                try:
                    ssl_context = ssl.create_default_context()
                    ssl_context.load_cert_chain("socket_certs/client.crt", "socket_certs/client.key")
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                except Exception as e:
                    print(f"[WS][SSL ERROR] Failed to create SSL context: {e}")

            async with websockets.connect(url, ssl=ssl_context, ping_interval=15, ping_timeout=10) as websocket:
                self.status_label_ws.setText("🟢 WS: Connected")
                self.ws_connected = True
                if not hasattr(self, "_ws_flare_triggered"):
                    self._ws_flare_triggered = False

                if not self._ws_flare_triggered:
                    self.status_label_ws.setStyleSheet("color: #33ff33; font-weight: bold; background-color: #003300;")
                    QTimer.singleShot(3000, lambda: self.status_label_ws.setStyleSheet(
                        "color: #33ff33; background-color: transparent;"))
                    self._ws_flare_triggered = True

                print("[WS] WebSocket connection established.")
                await websocket.send(json.dumps({
                    "type": "diagnostic",
                    "msg": "HiveMonitor is online.",
                    "timestamp": time.time()
                }))
                while True:
                    try:
                        msg = await websocket.recv()
                        self.message_received.emit(msg)
                    except Exception as e:
                        print(f"[WS][RECEIVE ERROR] {e}")
                        break

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[WS][ERROR] Failed to connect to WebSocket: {e}")
            self.status_label_ws.setText("🔴 WS: Disconnected")
            self.ws_connected = False


    def handle_websocket_message_safe(self, msg: str):
        try:
            print(f"[WS] RAW MESSAGE: {msg}")
            data = json.loads(msg)
            # Use 'type' if it exists, otherwise fall back to 'handler'
            msg_type = data.get("type") or data.get("handler", "unknown")

            if msg_type == "health_report":
                report = data.get("content", {})
                target = report.get("target_universal_id", "unknown")
                source = report.get("source_probe", "unknown")
                status = report.get("status", "unknown")
                heartbeat = report.get("last_heartbeat", "?")

                text = (
                    f"🧼 HEALTH REPORT\n"
                    f"• Target: {target}\n"
                    f"• Source Probe: {source}\n"
                    f"• Status: {status.upper()}\n"
                    f"• Last heartbeat: {heartbeat} sec\n"
                    f"• UUID: {report.get('spawn_uuid')}\n"
                )

                # Store last report for GUI panel
                self.last_probe_report[target] = report

                # Update display panel if selected
                if self.current_selected_uid == target:
                    QTimer.singleShot(0, lambda: self.handle_tree_click(self.find_tree_item_by_uid(target)))

                if msg_type == "health_report":
                    return  # 💣 completely skip appending

                if msg_type == "health_report":
                    report = data.get("content", {})
                    target = report.get("target_universal_id", "unknown")

                    # 🛑 BLOCK health logs from flooding log viewer
                    if self.user_requested_log_view and self.log_input.text().strip() == target:
                        print(f"[WS][SKIP] Blocking health_report for {target} from log viewer")
                        return

                else:
                    summary = f"[{msg_type.upper()}] {json.dumps(data.get('content', data), indent=2)[:200]}"
                    QTimer.singleShot(0, lambda: self.append_ws_feed_message(summary))


            #sent to websocket feed
            if msg_type in ("alert", "cmd_alert_to_gui"):
                content = data.get("content", {})
                level = content.get("level", "info").lower()
                embed = content.get("embed_data")

                # If we have rich embed data, parse it into a multi-line block
                if embed:
                    lines_to_display = []
                    title = embed.get('title', 'ALERT')
                    description = embed.get('description', '')
                    footer = embed.get('footer', '')

                    lines_to_display.append(f"--- 🔬 {title.upper()} 🔬 ---")

                    # Split the description by newlines and clean up Markdown for the GUI
                    for line in description.split('\\n'):  # Use \\n to split the literal newline characters
                        cleaned_line = line.replace('**', '').replace('`', '').replace('---', '---')
                        lines_to_display.append(f"  {cleaned_line}")

                    lines_to_display.append(f"--- {footer} ---")
                    lines_to_display.append(" ")  # Add a blank line for spacing

                    # Add each line as a separate item to the feed
                    for line in lines_to_display:
                        self.append_ws_feed_message(line, level=level)

                # Otherwise, fall back to the simple text display
                else:
                    msg_text = content.get("formatted_msg") or content.get("msg", "[No message]")
                    origin = content.get("origin", "?")
                    summary = f"[ALERT] {msg_text} ← {origin}"
                    self.append_ws_feed_message(summary, level=level)

                return

            else:

                if isinstance(msg_type, str):
                    handler_func = getattr(self.alert_panel, msg_type, None)
                    print(msg_type)
                    if callable(handler_func):
                        try:
                            handler_func(data.get("content", {}), data)
                        except Exception as e:
                            print(f"[HANDLER][ERROR] Failed to handle {msg_type}: {e}")

                else:
                    print(f"[WS][WARN] Invalid message type: {msg_type}")

                # all other message types

                #if self.user_requested_log_view:
                #    print("[WS][SKIP] User is actively viewing logs, ignoring unsolicited update.")

                #    return

                #text = json.dumps(data, indent=2)

                #QTimer.singleShot(0, lambda: self.log_text.append(text))

            #summary = f"[{msg_type.upper()}] {data.get('content', str(data))[:100]}"
            #QTimer.singleShot(0, lambda: self.append_ws_feed_message(summary))


        except Exception as e:
            print(f"[WS][ERROR] Could not parse WebSocket msg: {msg}\n{e}")

    def append_ws_feed_message(self, text, level="info", is_html=False):
        """
                Appends a message to the WebSocket feed, now with HTML support.
                """
        item = QListWidgetItem(self.ws_feed_display)  # Set parent

        if is_html:
            label = QLabel(text)
            label.setWordWrap(True)
            label.setStyleSheet("background-color: transparent; border: none; padding: 2px;")
            item.setSizeHint(label.sizeHint())
            self.ws_feed_display.addItem(item)
            self.ws_feed_display.setItemWidget(item, label)
        else:
            item.setText(text)  # Original behavior for plain text
            self.ws_feed_display.addItem(item)

        # Apply color based on level
        if level == "critical":
            item.setForeground(QColor("#ff3333"))  # red
            QSound.play("sounds/siren.wav")
        elif level == "warning":
            item.setForeground(QColor("#ffcc00"))  # yellow
            QSound.play("sounds/ping.wav")
        elif level == "info":
            item.setForeground(QColor("#33ff33"))  # green
        else:
            item.setForeground(QColor("#aaaaaa"))  # gray/fallback

        self.ws_feed_display.addItem(item)

        if self.ws_feed_display.autoscroll_enabled:
            self.ws_feed_display.scrollToBottom()

    def _safe_log_append(self, text):
        #if self.log_text.document().blockCount() > 500:
        #    self.log_text.setPlainText("")

        #self.log_text.append(line)

        # Enforce log limit
        limit_text = self.log_limit_box.currentText()
        limit = int(limit_text.split()[0]) if limit_text else 500

        if limit > 0 and self.log_text.document().blockCount() > limit:
            cursor = self.log_text.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.select(cursor.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    def handle_tree_click(self, item):
        try:
            universal_id = item.data(Qt.UserRole)
            if not universal_id:
                print("[WARN] Clicked tree item has no universal_id.")
                return

            print(f"[CLICK] Tree node selected: {universal_id}")
            self.current_selected_uid = universal_id



            # 🧠 Lookup node data
            node = self.agent_tree_flat.get(universal_id)
            if not node:
                print(f"[ERROR] No node found in flat tree for: {universal_id}")
                return

            self.log_input.setText(universal_id)
            self.view_logs()

            # 🔊 Emit node event (for external probe requests etc.)
            node_event_bus.node_selected.emit(universal_id)

            # 🧠 Populate fields
            self.input_agent_name.setText(node.get("name", ""))
            self.input_universal_id.setText(universal_id)
            self.input_target_universal_id.setText(universal_id)
            delegates = node.get("delegated", [])
            self.input_delegated.setText(",".join(delegates) if isinstance(delegates, list) else "")
            self.user_requested_log_view = False

            # 🧩 Update GUI state
            self.hotswap_btn.setEnabled(True)
            if hasattr(self, "log_panel"):
                self.log_panel.append(f"[GUI] Selected agent: {universal_id}")

            # 📋 Build info panel
            info_lines = [
                f"🧠 Name: {node.get('name', '')}",
                f"🏠 Universal ID: {universal_id}",
                f"👥 Delegates: {', '.join(delegates) if delegates else 'None'}",
                f"📁 Filesystem: {json.dumps(node.get('filesystem', {}), indent=2)}",
                f"⚙️ Config: {json.dumps(node.get('config', {}), indent=2)}"
            ]



            last_report = self.last_probe_report.get(universal_id)
            if last_report:

                cpu = last_report.get("cpu_percent")
                mem = last_report.get("memory_percent")

                if cpu is not None:
                    info_lines.append(f"🧬 CPU Usage: {cpu:.2f}%")
                else:
                    info_lines.append("🧬 CPU Usage: Unknown")

                if mem is not None:
                    info_lines.append(f"🧠 Memory Usage: {mem:.2f}%")
                else:
                    info_lines.append("🧠 Memory Usage: Unknown")

                info_lines.append(f"🛰️ Confirmed by: {last_report.get('source_probe', 'unknown')}")
                info_lines.append(f"⏱️ Heartbeat age: {last_report.get('last_heartbeat')} sec")
                info_lines.append(f"📦 UUID: {last_report.get('spawn_uuid')}")
                info_lines.append(f"🧬 CPU: {last_report.get('cpu_percent', '?')}%")
                info_lines.append(f"🧠 Memory: {last_report.get('memory_percent', '?')}%")
                info_lines.append(f"📡 Beacon: {last_report.get('beacon_status', 'unknown')}")
                info_lines.append(f"💥 Threads: {', '.join(last_report.get('dead_threads', [])) or 'All alive'}")

                # 🧩 Show thread beacon data
                threads = last_report.get("thread_status", {})
                if threads:
                    info_lines.append("📡 Thread Beacons:")
                    for thread, status in threads.items():
                        info_lines.append(f"   └─ {thread}: {status}")


            self.agent_info_panel.setText("\n".join(info_lines))

            # 📜 Update log view
            self.log_input.setText(universal_id)
            self.view_logs()

            # 📡 Send fresh status ping to Matrix
            status_payload = {
                "handler": "cmd_agent_status_report",
                "timestamp": time.time(),
                "content": {
                    "target_universal_id": universal_id,
                    "reply_to": "gui-agent"
                }
            }

            @run_in_thread(
                callback=lambda resp: print(
                    f"[STATUS_REQUEST] Dispatched for {universal_id}") if resp.status_code == 200 else print(
                    f"[STATUS_REQUEST][FAIL] Matrix returned {resp.status_code}"),
                error_callback=lambda err: print(f"[STATUS_REQUEST][ERROR] {err}")
            )
            def task():
                return requests.post(
                    url=self.matrix_host,
                    json=status_payload,
                    cert=CLIENT_CERT,
                    verify=False,
                    timeout=REQUEST_TIMEOUT
                )

            #task()

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[TREE-CLICK][CRASH] {e}")
            self.agent_info_panel.setText("⚠️ Failed to load agent info.")




    def find_tree_item_by_uid(self, uid):
        for i in range(self.tree_display.count()):
            item = self.tree_display.item(i)
            if item and item.data(Qt.UserRole) == uid:
                return item
        return None

    def send_status_request(self, uid):
        status_payload = {
            "handler": "cmd_agent_status_report",
            "timestamp": time.time(),
            "content": {
                "target_universal_id": uid,
                "reply_to": "gui-agent"
            }
        }

        try:
            response = requests.post(
                url=self.matrix_host,
                json=status_payload,
                cert=CLIENT_CERT,
                verify=False,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                print(f"[STATUS_REQUEST] Dispatched for {uid}")
            else:
                print(f"[STATUS_REQUEST][FAIL] Matrix returned {response.status_code}")
        except Exception as e:
            print(f"[STATUS_REQUEST][ERROR] {e}")

    def toggle_status_dot(self):
        if hasattr(self, "status_label_ws") and "Connected" in self.status_label_ws.text():
            dot = "🟢" if self.pulse_state else "⚫"
            self.status_label_ws.setText(f"{dot} WS: Connected")
            self.pulse_state = not self.pulse_state

        if hasattr(self, "status_label_matrix") and "Connected" in self.status_label_matrix.text():
            dot = "🟢" if self.pulse_state else "⚫"
            self.status_label_matrix.setText(f"{dot} Matrix: Connected")

    def build_command_view(self):
        container = QWidget()
        layout = QHBoxLayout(container)

        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.addWidget(self.build_command_panel())
        left_layout.addWidget(self.build_autoscroll_left_panel())
        self.center_panel = self.build_tree_panel()
        self.right_panel = self.build_log_panel()




        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.center_panel)
        splitter.addWidget(self.right_panel)
        splitter.setSizes([300, 800, 300])
        splitter.setStretchFactor(0, 0)  # Left panel
        splitter.setStretchFactor(1, 1)  # Center panel grows/shrinks most
        splitter.setStretchFactor(2, 0)  # Right panel
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, False)
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

    def pass_log_result(self, uid):
        def _handler(result):
            self._handle_logs_result(result, uid)

        return _handler

    def forward_to_health_probe(self, target_uid):

        if not target_uid:
            return

        probe_uid = "health-probe-oracle-1"  # ✅ always send to probe

        payload = {
            "handler": "cmd_forward_command",
            "timestamp": time.time(),
            "content": {
                "target_universal_id": probe_uid,
                "folder": "incoming",
                "command": {
                    "handler": "agent_status_report",
                    "filetype": "msg",
                    "content": {
                        "target_universal_id": target_uid
                    }
                }
            }
        }


        return


        try:
            response = requests.post(
                url=self.matrix_host,
                json=payload,
                cert=CLIENT_CERT,
                verify=False,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                print(f"[HEALTH-FORWARD] Probe sent to {probe_uid} for {target_uid}")
            else:
                print(f"[HEALTH-FORWARD][FAIL] Matrix returned {response.status_code}")
        except Exception as e:
            print(f"[HEALTH-FORWARD][ERROR] {e}")

    def send_payload_to_matrix(self, success_message="Payload delivered."):
        payload_text = self.payload_editor.toPlainText().strip()
        if not payload_text:
            self.status_label.setText("⚠️ No payload to send.")
            return

        try:
            raw_input = self.payload_editor.toPlainText().strip()
            parsed = json.loads(raw_input)

            if not isinstance(parsed, dict):
                raise ValueError("Payload must be a JSON object.")

            if "handler" not in parsed:
                raise ValueError("Missing required field: 'handler'")

        except json.JSONDecodeError as e:
            self.status_label.setText(f"⚠️ Invalid JSON: {e}")
            return
        except ValueError as e:
            self.status_label.setText(f"⚠️ {e}")
            return


        target = self.dropdown_target_uid.currentText().strip()
        if not target:
            self.status_label.setText("⚠️ No target selected.")
            return

        pk1 = self.get_delivery_packet("standard.command.packet")
        pk1.set_data({
            "handler": "cmd_forward_command"
        })

        pk2 = self.get_delivery_packet("standard.general.json.packet")
        pk2.set_data({
            "target_universal_id": target,
            "folder": self.folder_selector.currentText()
        })

        pk3 = self.get_delivery_packet("standard.general.json.packet")
        pk3.set_data(parsed)  # validate + prep internal metadata

        pk2.set_auto_fill_sub_packet(False) \
           .set_packet(pk3, "command")

        pk1.set_auto_fill_sub_packet(False) \
            .set_packet(pk2, "content")

        print(pk1.get_packet())

        try:
            response = requests.post(
                url=self.matrix_host,
                json = pk1.get_packet(),
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

    def handle_alarm_message(self, msg):
        alarm = json.loads(msg)
        print(f"🔥 ALARM RECEIVED: {alarm}")
        self.status_label.setText(f"🚨 {alarm.get('universal_id')} ALERT: {alarm.get('cause')}")

    def view_logs(self):

        universal_id = self.log_input.text().strip().split(" ")[0]

        if not universal_id:
            print("[LOG] ❌ No universal_id set for log fetch.")
            return

        self.user_requested_log_view = True
        print(f"[LOG] View Logs requested for: {universal_id}")

        payload = {
            "handler": "cmd_get_log",
            "timestamp": time.time(),
            "content": {"universal_id": universal_id}
        }

        def threaded_log_fetch():
            try:
                print(f"[THREAD] Sending log request for {universal_id}")
                response = requests.post(
                    url=self.matrix_host,
                    json=payload,
                    cert=CLIENT_CERT,
                    verify=False,
                    timeout=REQUEST_TIMEOUT
                )
                print(f"[THREAD] Response code: {response.status_code}")

                try:
                    parsed_json = response.json()
                except Exception as json_error:
                    print(f"[THREAD] JSON parse failed: {json_error}")
                    parsed_json = {}

                result = {
                    "status_code": response.status_code,
                    "text": response.text,
                    "json": parsed_json
                }

                self.log_ready.emit(result, universal_id)  # 🔥 Safe signal to GUI thread

            except Exception as e:
                print(f"[THREAD][EXCEPTION] {e}")
                QTimer.singleShot(0, lambda: self.log_text.setPlainText(f"[ERROR] {str(e)}"))

        threading.Thread(target=threaded_log_fetch, daemon=True).start()

    def _handle_logs_result(self, result, uid):
        print(f"[UI] Handling log result for {uid}")

        try:
            log_data = result["json"]["log"]
        except (KeyError, TypeError):
            log_data = "[ERROR] No decrypted log returned from Matrix."

        if not log_data:
            print(f"[ERROR] No log data found for {uid}")
            self.log_text.setPlainText(f"[NO LOG DATA FOUND] for {uid}")
            return

        # 🧪 Optional decode if server double-escaped
        if isinstance(log_data, str) and "\\u" in log_data:
            import codecs
            try:
                log_data = codecs.decode(log_data, "unicode_escape")
                print(f"[DEBUG] Unicode decoded log for {uid}")
            except Exception as e:
                print(f"[WARN] Unicode decode failed: {e}")

        self.log_text.clear()
        self.log_text.setVisible(True)
        self.log_text.setPlainText(log_data)
        self.log_text.moveCursor(self.log_text.textCursor().End)
        self.log_text.ensureCursorVisible()
        self._log_poll_busy = False

    def scroll_log_to_bottom(self):
        self.log_text.moveCursor(self.log_text.textCursor().End)
        self.log_text.ensureCursorVisible()

    def build_log_panel(self):
        box = QGroupBox("📡 Agent Intel Logs")
        box.setObjectName("log_panel")
        layout = QVBoxLayout()

        # ───────────── Host/IP Change Row ─────────────
        self.host_input = QLineEdit(self.matrix_host)
        self.host_input.setPlaceholderText("Enter Matrix Host (e.g., https://1.2.3.4:65431/matrix)")

        set_host_btn = QPushButton("Set Host/IP")
        set_host_btn.clicked.connect(self.change_matrix_host)

        host_layout = QHBoxLayout()
        host_layout.addWidget(QLabel("Matrix Host:"))
        host_layout.addWidget(self.host_input)
        host_layout.addWidget(set_host_btn)
        layout.addLayout(host_layout)
        # ───────────────────────────────────────────────────
        self.log_input = QLineEdit()
        self.log_input.setPlaceholderText("Enter agent universal_id to view logs")
        self.log_input.setStyleSheet("background-color: #000; color: #33ff33; border: 1px solid #00ff66;")

        view_btn = QPushButton("View Logs")
        view_btn.clicked.connect(self.view_logs)
        print("[DEBUG] View Logs button wired.")
        view_btn.setStyleSheet("background-color: #111; color: #33ff33; border: 1px solid #00ff66;")

        self.log_text = QTextEdit()
        self.log_text.setLineWrapMode(QTextEdit.WidgetWidth)
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

        self.log_limit_box = QComboBox()
        self.log_limit_box.addItems(["0 (unlimited)", "100", "500", "1000"])
        self.log_limit_box.setCurrentIndex(0)  # default to unlimited
        layout.addWidget(QLabel("Limit:"))
        layout.addWidget(self.log_limit_box)

        self.auto_scroll_checkbox = QCheckBox("Auto-scroll logs")
        self.auto_scroll_checkbox.setChecked(True)
        self.auto_scroll_checkbox.setStyleSheet("color: #33ff33; font-family: Courier;")
        layout.addWidget(self.auto_scroll_checkbox)

        box.setMinimumWidth(300)

        layout.addWidget(self.log_input)
        layout.addWidget(view_btn)
        layout.addWidget(self.log_text)
        box.setLayout(layout)
        return box

    #REFRESH AGENT TREE EVER 10 sec's
    def start_tree_autorefresh(self, interval=10):
        self.tree_timer = QTimer(self)
        self.tree_timer.timeout.connect(self.request_tree_from_matrix)
        self.tree_timer.start(interval * 1000)

    #Retreive the agent Tree
    def request_tree_from_matrix(self):

        self.tree_stack.setCurrentIndex(0)  # Show loading
        try:

            payload = {"handler": "cmd_list_tree", "timestamp": time.time(), "content": {}}
            response = requests.post(
                url=self.matrix_host,
                json=payload,
                cert=CLIENT_CERT,
                verify=False,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                self.status_label_matrix.setText("🟢 Connected")
                tree = response.json().get("tree", {})
                self.render_tree_to_gui(tree)
            else:
                self.status_label_matrix.setText("🔴 Disconnected")


        except Exception as e:
            self.status_label_matrix.setText("🔴 Disconnected")
            print(str(e))
        self.tree_stack.setCurrentIndex(1)  # Show tree

    def render_tree_to_gui(self, tree):
        output = self.render_tree(tree)  # (line, universal_id, color)
        self.tree_display.clear()

        self.agent_tree_flat = {}

        def recurse_flatten(node):
            if not isinstance(node, dict):
                return
            uid = node.get("universal_id")
            if uid:
                self.agent_tree_flat[uid] = node
            for child in node.get("children", []):
                recurse_flatten(child)

        recurse_flatten(tree)
        self.populate_target_dropdown()

        # 🧠 Add timestamp header
        header = QListWidgetItem(f"[MATRIX TREE @ {time.strftime('%H:%M:%S')}]")
        header.setForeground(QColor("#888"))
        header.setFlags(header.flags() & ~Qt.ItemIsSelectable)  # make header unclickable
        self.tree_display.addItem(header)

        # 🔍 Track current UID for reselect
        current_uid = self.input_universal_id.text().strip()

        for line, universal_id, color in output:
            item = QListWidgetItem(line)
            item.setData(Qt.UserRole, universal_id)
            item.setForeground(QColor("#33ff33") if color == "green" else QColor("#ff5555"))
            self.tree_display.addItem(item)


            if universal_id == current_uid:
                self.tree_display.setCurrentItem(item)
                self.tree_display.scrollToItem(item)

    def render_tree(self, node, indent="", is_last=True):
        output = []
        if not isinstance(node, dict):
            output.append((f"{indent} Retrieving Agent Listing...", "none", "red"))
            return output
        #hide deleted nodes
        deleted = bool(node.get('deleted', False))
        if deleted:
            return ""

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
        tomb_path = os.path.join("comm", universal_id, "incoming", "tombstone")

        if os.path.exists(die_path):
            universal_id += " 💤"
            color = "gray"

        elif os.path.exists(tomb_path):
            universal_id += " ⚰️"
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
            if self.agent_tree_flat.get(target_uid):
                deploy_data["name"] = target_uid  # use existing name
            else:
                suffix = self.random_suffix(5)
                deploy_data["name"] = f"{base_name}_bp_{suffix}"

                # 🧠 Inject encoded source and SHA256
            deploy_data["source_payload"] = {
                "payload": encoded,
                "sha256": file_hash
            }

            # 🎯 Final payload
            payload = {
                "handler": "cmd_hotswap_agent",
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

    def populate_target_dropdown(self):

        self.dropdown_target_uid.clear()

        if not hasattr(self, "agent_tree_flat") or not self.agent_tree_flat:
            return

        agents = sorted(self.agent_tree_flat.keys())
        self.dropdown_target_uid.addItems(agents)
        self.dropdown_target_uid.setCurrentText("websocket-relay")  # Optional default

        last_target = self.input_universal_id.text().strip()
        if last_target in agents:
            self.dropdown_target_uid.setCurrentText(last_target)

    @staticmethod
    def render_log_line(entry: dict) -> str:
        emoji = {
            "INFO": "🔹",
            "WARNING": "⚠️",
            "ERROR": "❌",
            "DEBUG": "🐞"
        }
        ts = entry.get("timestamp", "??")
        level = entry.get("level", "INFO").upper()
        prefix = emoji.get(level, "🟢")
        msg = entry.get("message", "[NO MESSAGE]")
        return f"{prefix} [{ts}] [{level}] {msg}"

    def build_command_panel(self):
        box = QGroupBox("🧩 Mission Console")
        box.setObjectName("mission_panel")
        layout = QVBoxLayout()
        layout.setSpacing(6)

        self.input_agent_name = QLineEdit("agent_name")
        self.input_universal_id = QLineEdit("universal_id")
        self.input_target_universal_id = QLineEdit("target_universal_id")
        self.input_delegated = QLineEdit("comma,separated,delegated")

        for widget in [self.input_agent_name, self.input_universal_id, self.input_target_universal_id, self.input_delegated]:
            widget.setStyleSheet("background-color: #000; color: #33ff33; border: 1px solid #00ff66;")
            layout.addWidget(widget)

        #zipcode change for sever weather
        #_label = QLabel("Update Zipcode")
        #zipcode_label.setStyleSheet("color: #33ff33; font-family: Courier;")
        #layout.addWidget(zipcode_label)

        #self.zipcode_entry = QLineEdit()
        #self.zipcode_entry.setPlaceholderText("Enter ZIP code, e.g. 90210")
        #self.zipcode_entry.setStyleSheet("background-color: #000; color: #33ff33; border: 1px solid #00ff66;")
        #layout.addWidget(self.zipcode_entry)

        #push_btn = QPushButton("📡 Push Zip to Agent")
        #push_btn.clicked.connect(self.push_zipcode_to_agent)
        #layout.addWidget(push_btn)

        self.hotswap_btn = QPushButton("🔥 Hotswap")
        self.hotswap_btn.clicked.connect(self.hotswap_agent_code)
        self.hotswap_btn.setToolTip("Replace the agent's logic with a live hot-swapped source file.")
        self.hotswap_btn.setStyleSheet("background-color: #1e1e1e; color: #ff4444; border: 1px solid #00ff66;")
        self.hotswap_btn.setEnabled(False)
        layout.addWidget(self.hotswap_btn)

        layout.addWidget(QLabel("🎯 Target Agent (universal_id):"))
        self.dropdown_target_uid = QComboBox()
        self.dropdown_target_uid.setEditable(True)
        self.dropdown_target_uid.setStyleSheet("background-color: black; color: #00ffcc; font-family: Courier;")
        self.dropdown_target_uid.setInsertPolicy(QComboBox.NoInsert)
        layout.addWidget(self.dropdown_target_uid)

        self.folder_selector = QComboBox()
        self.folder_selector.addItems(["incoming", "payload", "queue", "stack", "replies", "broadcast", "config"])
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

    def push_zipcode_to_agent(self):

        try:
            zip_code = self.zipcode_entry.get().strip()
            target_uid = self.input_universal_id.text().strip()

            if not zip_code or not target_uid:
                QMessageBox.warning(self, "Missing Info", "Enter a zipcode and select a target agent.")
                return

            payload = {
                "type": "cmd_update_agent",
                "timestamp": time.time(),
                "content": {
                    "target_universal_id": target_uid,
                    "config": {
                        "zip-code": zip_code
                    },
                    "push_live_config": True
                }
            }

            try:
                import requests
                response = requests.post(
                    url=self.matrix_host,
                    json=payload,
                    cert=CLIENT_CERT,
                    verify=False,
                    timeout=REQUEST_TIMEOUT
                )

                if response.status_code == 200:
                    QMessageBox.warning(self, "Success", f"Zipcode {zip_code} pushed to {target_uid}.")
                else:
                    QMessageBox.warning(self, "Matrix Error", f"{response.status_code}: {response.text}")
            except Exception as e:
                QMessageBox.warning(self, "Connection Failed", str(e))

        except Exception as e:
            print(f"{e}")

    def send_reboot_agent(self):

        from PyQt5.QtWidgets import QMessageBox

        confirm = QMessageBox.question(self, "Confirm Reboot",
                                       "⚠️ This will trigger a hard system reboot via bootloader.\nProceed?",
                                       QMessageBox.Yes | QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return

        payload = {
            "handler": "cmd_spawn_agent",
            "timestamp": time.time(),
            "content": {
                "agent_name": "reboot_agent",
                "universal_id": "reboot-1",
                "filesystem": {},
                "config": {
                    "confirm": "YES",
                    "shutdown_all": True,
                    "reboot_matrix": True
                }
            }
        }

        requests.post(
            url=self.matrix_host,
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
            "handler": "cmd_delete_agent",
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
                with open(os.path.join(codex_dir, file), encoding="utf-8") as f:
                    data = json.load(f)
                    entry = f"🧬 {data.get('universal_id', '???')} – {data.get('title', 'Untitled')}\n{data.get('summary', '')}"
                    entries.append(entry)
            except Exception as e:
                entries.append(f"[ERROR] Failed to load {file}: {e}")

        self.codex_display.setPlainText("\n\n".join(entries) if entries else "[CODEX] Empty.")

    def check_matrix_connection(self):
        try:
            response = requests.get(
                url=self.matrix_host + "/ping",
                cert=CLIENT_CERT,
                verify=False,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                self.status_label_matrix.setText("🟢 Matrix: Connected")
            else:
                self.status_label_matrix.setText("🔴 Matrix: Disconnected")
        except Exception as e:
            self.status_label_matrix.setText("🔴 Matrix: Disconnected")
            print(str(e))

    def build_tree_panel(self):
        box = QGroupBox("🧠 Hive Tree View")
        box.setObjectName("tree_group")
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
        self.reaper_btn = QPushButton("📈 Crypto Alerts")
        self.reaper_btn.clicked.connect(lambda: self.stack.setCurrentWidget(self.alert_panel))
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
        self.delete_btn.clicked.connect(self.handle_delete_agent)


        layout.addLayout(self.tree_stack)
        layout.addWidget(reload_btn)
        box.setLayout(layout)
        return box

    def handle_resume_agent(self):
        universal_id = self.input_universal_id.text().strip()
        if not universal_id:
            self.status_label.setText("⚠️ No agent selected.")
            return

        payload = {
            "handler": "cmd_resume_subtree",
            "timestamp": time.time(),
            "content": {
                "universal_id": universal_id
            }
        }

        self.send_post_to_matrix(payload, f"Resume signal sent to subtree under {universal_id}")

    def handle_shutdown_agent(self):
        universal_id = self.input_universal_id.text().strip()
        if not universal_id:
            self.status_label.setText("⚠️ No agent selected.")
            return

        payload = {
            "handler": "cmd_shutdown_subtree",
            "timestamp": time.time(),
            "content": {
                "universal_id": universal_id
            }
        }

        self.send_post_to_matrix(payload, f"Shutdown signal sent to subtree under {universal_id}")

            #INJECT AGENT INTO TREE
    def handle_inject_to_tree(self):
        import base64, os, hashlib, json, random
        from PyQt5.QtWidgets import QFileDialog

        def random_suffix(length=5):
            return ''.join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=length))

        file_name, _ = QFileDialog.getOpenFileName(self, "Select Agent or Directive", "",
                                                   "Python or JSON Files (*.py *.json)")
        if not file_name:
            return

        suffix = "_" + random_suffix(5)
        payload = None

        # ──────────────────────────────
        # 🧠 CASE: JSON TEAM FILE
        # ──────────────────────────────
        if file_name.endswith(".json"):
            with open(file_name, encoding="utf-8") as f:
                data = json.load(f)

            def recurse_suffix(node):
                if "universal_id" in node:
                    node["universal_id"] += suffix
                for child in node.get("children", []):
                    recurse_suffix(child)
                return node

            data = recurse_suffix(data)
            self.inject_sources_into_tree(data)

            payload = {
                "handler": "cmd_inject_agents",
                "timestamp": time.time(),
                "content": {
                    "target_universal_id": self.input_target_universal_id.text().strip(),
                    "subtree": data
                }
            }

        # ──────────────────────────────
        # 🧠 CASE: SINGLE .py AGENT
        # ──────────────────────────────
        elif file_name.endswith(".py"):
            with open(file_name, "rb", encoding="utf-8") as f:
                code = f.read()
            encoded = base64.b64encode(code).decode()
            sha = hashlib.sha256(code).hexdigest()

            agent_name = os.path.basename(file_name).replace(".py", "")
            base_path = os.path.dirname(file_name)
            directive_path = os.path.join(base_path, "deploy_directive.py")

            if os.path.exists(directive_path):
                import importlib.util
                spec = importlib.util.spec_from_file_location("deploy_directive", directive_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                directive = module.directive
            else:
                directive = {}


            if "name" not in directive:
                directive["name"] = agent_name

            if "universal_id" not in directive:
                directive["universal_id"] = agent_name  # default fallback


            # Ensure universal_id exists and suffix it
            uid = directive.get("universal_id", agent_name)
            directive["universal_id"] = uid + suffix
            directive.setdefault("filesystem", {})
            directive.setdefault("config", {})
            directive["source_payload"] = {
                "payload": encoded,
                "sha256": sha
            }

            payload = {
                "handler": "cmd_inject_agents",
                "timestamp": time.time(),
                "content": {
                    "target_universal_id": self.input_target_universal_id.text().strip(),
                    **directive
                }
            }
            print("🧠 INJECT PAYLOAD:", json.dumps(payload, indent=2))

        if payload:
            self.send_post_to_matrix(payload, f"Injected {payload['content'].get('agent_name', 'team')} ✅")

    def inject_sources_into_tree(self, node):
        name = node.get("name")
        if name:
            path = os.path.join("inject_payloads", f"{name}.py")
            if os.path.exists(path):
                with open(path, "rb", encoding="utf-8") as f:
                    code = f.read()
                    encoded = base64.b64encode(code).decode()
                    sha = hashlib.sha256(code).hexdigest()
                    node["source_payload"] = {
                        "payload": encoded,
                        "sha256": sha
                    }
        for child in node.get("children", []):
            self.inject_sources_into_tree(child)



    def handle_delete_subtree(self):
        universal_id = self.input_universal_id.text().strip()
        if not universal_id:
            self.status_label.setText("⚠️ No agent selected.")
            return

        payload = {
            "handler": "cmd_delete_subtree",
            "timestamp": time.time(),
            "content": {
                "universal_id": universal_id
            }
        }

        self.send_post_to_matrix(payload, f"Subtree delete issued for {universal_id}")

    def send_post_to_matrix(self, payload, success_message):
        @run_in_thread(
            callback=lambda resp: self.status_label.setText(f"✅ {success_message}") if resp.status_code == 200
            else self.status_label.setText(f"❌ Matrix error: {resp.status_code}"),
            error_callback=lambda err: self.status_label.setText(f"❌ Connection failed: {err}")
        )
        def task():
            return requests.post(
                url=self.matrix_host,
                json=payload,
                cert=CLIENT_CERT,
                verify=False,
                timeout=REQUEST_TIMEOUT
            )

        task()


    def open_file_picker(self):
        QTimer.singleShot(0, self._open_picker_blocking)

    def _open_picker_blocking(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Select File", "", "Python or JSON Files (*.py *.json)")
        if file_name:
            self.process_injection_file(file_name)

    def post_async(self, payload, on_success=None, on_fail=None):
        def worker():
            try:
                response = requests.post(self.matrix_host, json=payload, cert=CLIENT_CERT, verify=False, timeout=REQUEST_TIMEOUT)
                if response.status_code == 200 and on_success:
                    QTimer.singleShot(0, lambda: on_success(response))
                elif on_fail:
                    QTimer.singleShot(0, lambda: on_fail(response))
            except Exception as e:
                if on_fail:
                    QTimer.singleShot(0, lambda: on_fail(e))
        threading.Thread(target=worker, daemon=True).start()

    def build_autoscroll_left_panel(self):
        box = QGroupBox("📡 Incoming WebSocket Feed")
        box.setObjectName("ws_feed_panel")
        layout = QVBoxLayout()

        self.ws_feed_display = AutoScrollList()
        self.ws_feed_display.setStyleSheet("""
            QListWidget {
                background-color: #000000;
                color: #33ff33;
                font-family: Courier;
                font-size: 13px;
                border: 1px solid #00ff66;
            }
            QListWidget::item {
                padding: 2px;
            }
        """)

        layout.addWidget(self.ws_feed_display)
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
            font-family: Consolas, Courier, monospace;
            font-size: 13px;
        }

        QLineEdit, QTextEdit, QListWidget, QPushButton, QComboBox {
            background-color: #000;
            color: #33ff33;
            border: 1px solid #00ff66;
            padding: 4px;
        }

        QComboBox::drop-down {
            width: 24px;
            subcontrol-origin: padding;
            subcontrol-position: top right;
            border-left: 1px solid #00ff66;
        }

        QComboBox::down-arrow {
            image: none;
            width: 14px;
            height: 14px;
            border: 1px solid #00ff66;
            border-radius: 4px;
            background-color: #00ff66;
        }

        QComboBox QAbstractItemView {
            background-color: #111;
            border: 1px solid #00ff66;
            selection-background-color: #00ff66;
            selection-color: #000;
        }

        QGroupBox {
            border: none;  /* ✅ Kill the default box */
            background-color: #101010;
            border-radius: 8px;
            padding: 10px;
            margin: 8px 0;
        }

        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 6px;
            color: #00ff66;
        }

        QPushButton:hover {
            background-color: #1e1e1e;
        }
        QGroupBox#tree_group, QGroupBox#log_panel, QGroupBox#mission_panel, QGroupBox#ws_feed_panel {
            border: 1px solid #00ff66;
            border-radius: 4px;
            margin: 4px;
            padding: 6px;
            background-color: #111;
        }
    """)

    window = MatrixCommandBridge()
    window.show()
    sys.exit(app.exec_())
