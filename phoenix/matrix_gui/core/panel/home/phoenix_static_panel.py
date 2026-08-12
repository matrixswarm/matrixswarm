# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import json, time, hashlib, platform, winsound, subprocess, threading, os
from pathlib import Path
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QGroupBox, QComboBox, QCheckBox, QHBoxLayout
from matrix_gui.core.class_lib.feed.feed_formatter import FeedFormatter
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QMenu

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QGraphicsDropShadowEffect
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.core.event_bus import EventBus
class PhoenixStaticPanel(QWidget):
    """
    Home HUD after vault unlock:
      - Vault info (path + status)
      - Deployment summary
      - Swarm feed (ops console)
      - Quick ping box
    """
    def __init__(self, vault_data=None, vault_path=None,  parent=None, tab_widget=None, tab_index=None):
        super().__init__(parent)
        self.tab_widget = tab_widget
        self.tab_index = tab_index

        layout = QVBoxLayout(self)

        self.deployment_tree = QTreeWidget()

        self.deployment_tree.setHeaderHidden(True)

        self.deployment_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.deployment_tree.customContextMenuRequested.connect(self._on_deployment_context_menu)
        layout.addWidget(self.deployment_tree)

        self._recent_alerts = {}  # message-hash → timestamp

        # === Sound Controls ===
        sound_box = QGroupBox("🔈 Alert Sound Settings")
        sound_layout = QHBoxLayout()

        self.play_sound_checkbox = QCheckBox("Play sound")
        self.play_sound_checkbox.setChecked(True)

        self.sound_dropdown = QComboBox()
        self._populate_sound_list()

        sound_layout.addWidget(QLabel("Sound:"))
        sound_layout.addWidget(self.sound_dropdown, stretch=1)
        sound_layout.addWidget(self.play_sound_checkbox)
        sound_box.setLayout(sound_layout)
        layout.addWidget(sound_box)

        # === Swarm Feed ===
        self.feed = QTextEdit()
        self.feed.setReadOnly(True)
        layout.addWidget(self.feed)

        self.parent=parent
        self._has_unread_alert = False
        self._update_static_tab_indicator()

        # === Deployments summary ===
        deploy_box = QGroupBox("Deployments")
        deploy_layout = QVBoxLayout()
        deploy_layout.addWidget(self.deployment_tree)
        deploy_box.setLayout(deploy_layout)
        layout.addWidget(deploy_box)

        # === Swarm Feed ===
        feed_box = QGroupBox("🛰️ Swarm Feed")
        feed_layout = QVBoxLayout()
        feed_layout.addWidget(self.feed)
        feed_box.setLayout(feed_layout)
        layout.addWidget(feed_box)

        EventBus.on("vault.core.ready", self._refresh_deployment_summary)
        EventBus.on("vault.core.update", self._refresh_deployment_summary)

    def _vault(self):
        return VaultCoreSingleton.get().read()

    def _refresh_deployment_summary(self):
        try:
            self.deployment_tree.clear()
            vault = self._vault()
            deployments = vault.get("deployments", {})
            for dep_id, meta in deployments.items():
                if not isinstance(meta, dict):
                    continue
                label = meta.get("label", dep_id)
                dep_item = QTreeWidgetItem([f"📦 {label}"])
                dep_item.setData(0, Qt.ItemDataRole.UserRole, {"dep_id": dep_id, "meta": meta})
                self.deployment_tree.addTopLevelItem(dep_item)

                for agent in meta.get("agents", []):
                    uid = agent.get("universal_id")
                    conn = agent.get("connection", {})
                    proto = conn.get("proto", "?")
                    host = conn.get("host", "?")
                    port = conn.get("port", "?")
                    child = QTreeWidgetItem([f"{uid} ({proto}) {host}:{port}"])
                    dep_item.addChild(child)
        except Exception as e:
            emit_gui_exception_log("PhoenixStaticPanel._refresh_deployment_summary", e)

    def handle_feed_event(self, event: dict):
        """Routes incoming events from session processes to the feed."""
        try:
            if not isinstance(event, dict):
                print("[FEED][WARN] Non-dict event:", event)
                return

            payload = event.get("payload", {})
            handler = payload.get("handler")

            # Inject deployment/session from session_window
            deployment = event.get("deployment", "unknown")
            session_id = event.get("session_id", "unknown")

            # If it’s an alert, go through _handle_swarm_alert()
            if handler == "swarm_feed.alert":
                # Merge context so alerts know their origin
                self._has_unread_alert = True
                self._update_static_tab_indicator()
                payload["deployment"] = deployment
                payload["session_id"] = session_id
                self._handle_swarm_alert(payload)
            else:
                # Normal event → format directly
                msg = FeedFormatter.format({
                    "deployment": deployment,
                    "session_id": session_id,
                    **event
                })
                self.feed.append(msg)

        except Exception as e:
            emit_gui_exception_log("PhoenixStaticPanel.handle_feed_event", e)

    def _append_feed_event(self, event: dict):
        """Append a formatted event to the Swarm Feed console."""
        try:
            msg = FeedFormatter.format(event)
            self.feed.append(msg)
        except Exception as e:
            emit_gui_exception_log("PhoenixStaticPanel._append_feed_event", e)

    def _on_inbound_message(self, session_id: str, channel: str, source: str, payload: dict, ts: float, **_):
        try:
            t = time.strftime("%H:%M:%S", time.localtime(ts))
            snippet = json.dumps(payload.get("content", payload), separators=(",", ":"), sort_keys=True)[:160]
            line = f"[{t}] ({channel}) {source} » sess={session_id} :: {snippet}"
            self.feed.append(line)
        except Exception as e:
            emit_gui_exception_log("PhoenixStaticPanel._on_inbound_message", e)

    def _update_static_tab_indicator(self):
        try:
            if not self.tab_widget or self.tab_index is None:
                return

            label = "🜂 Dashboard" if not self._has_unread_alert else "🔺 Dashboard"
            self.tab_widget.setTabText(self.tab_index, label)


        except Exception as e:
            emit_gui_exception_log("PhoenixStaticPanel._update_static_tab_indicator", e)


    def _handle_swarm_alert(self, payload: dict):
        """Handle alert packets with color, deduplication, and audio."""
        try:

            #print(f"{payload}")

            content = payload.get("content", {}) or {}
            msg = content.get("formatted_msg") or content.get("msg") or ""
            if not msg:
                return

            level = content.get("level", "INFO").upper()
            aliases = {
                "CRIT": "CRITICAL", "CRITICAL": "CRITICAL",
                "FATAL": "EMERGENCY", "SEVERE": "CRITICAL", "EMERG": "EMERGENCY",
            }
            level = aliases.get(level, level)

            origin = content.get("origin", "unknown")
            deployment = payload.get("deployment", "unknown")
            session_id = payload.get("session_id", "unknown")

            alert_id = content.get("id") or hashlib.md5(msg.encode()).hexdigest()
            now = time.time()
            if alert_id in self._recent_alerts and now - self._recent_alerts[alert_id] < 10:
                return
            self._recent_alerts[alert_id] = now

            event = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "event_type": "alert",
                "agent": origin,
                "details": msg,
                "level": level,
                "status": "active",
                "deployment": deployment,
                "session_id": session_id,
            }

            formatted = FeedFormatter.format(event)
            self.feed.append(formatted + "<br>")

            # --- play sound ---
            self._play_alert_sound()

        except Exception as e:
            emit_gui_exception_log("PhoenixStaticPanel._handle_swarm_alert", e)

    def _play_alert_sound(self):
        """Play the selected WAV through the OS if checkbox is on."""
        if not self.play_sound_checkbox.isChecked():
            return

        def _worker():
            try:

                sound_name = self.sound_dropdown.currentText()
                sound_path = os.path.abspath(f"matrix_gui/resources/sounds/{sound_name}")
                if platform.system() == "Windows":
                    winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["afplay", sound_path])
                else:
                    subprocess.Popen(["aplay", sound_path])
            except Exception as e:
                print(f"[ALERT-SOUND][ERROR] {e}")

        threading.Thread(target=_worker, daemon=True).start()


    def _on_deployment_context_menu(self, pos):

        try:
            item = self.deployment_tree.itemAt(pos)
            if not item:
                return

            data = item.data(0, Qt.ItemDataRole.UserRole)
            if not data:
                return  # only top-level deployment nodes

            menu = QMenu(self)
            act_connect = menu.addAction("🔌 Connect")
            act_connect.triggered.connect(lambda: self._connect_deployment(data))
            menu.exec(self.deployment_tree.viewport().mapToGlobal(pos))

        except Exception as e:
            emit_gui_exception_log("PhoenixStaticPanel._on_deployment_context_menu", e)

    def _populate_sound_list(self):
        """Scan the sounds folder and fill the dropdown."""
        try:
            sound_dir = Path("matrix_gui/resources/sounds")
            if not sound_dir.exists():
                self.sound_dropdown.addItem("alert.wav")
                return
            files = sorted(
                [p.name for p in sound_dir.glob("*.wav") if p.is_file()],
                key=str.lower,
            )
            if not files:
                self.sound_dropdown.addItem("alert.wav")
                return
            self.sound_dropdown.clear()
            for f in files:
                self.sound_dropdown.addItem(f)
            # default selection
            if "alert.wav" in files:
                self.sound_dropdown.setCurrentText("alert.wav")
        except Exception as e:
            print(f"[SOUND][WARN] Could not populate sound list: {e}")

    def _connect_deployment(self, data):
        try:
            dep_id = data["dep_id"]
            meta = data["meta"]
            print(f"[COCKPIT] Connecting to deployment {dep_id}…")

            EventBus.emit("session.open.requested", dep_id, meta, self.vault_data)
        except Exception as e:
            emit_gui_exception_log("PhoenixStaticPanel._connect_deployment", e)