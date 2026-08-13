import uuid, time, json
from PyQt6.QtWidgets import (QVBoxLayout, QMessageBox, QHBoxLayout, QLabel, QPushButton, QTextBrowser)
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.core.panel.custom_panels.interfaces.base_panel_interface import PhoenixPanelInterface
from PyQt6.QtCore import QMutex, Qt, QTimer, QUrl
from PyQt6.QtGui import QTextCursor

from collections import deque

class PluginGuard(PhoenixPanelInterface):
    """
    PluginGuard is a PyQt5-based panel interface for managing the
    WordPress Plugin Guard Agent.

    It provides a graphical interface for:
    - Displaying the status of all plugins (tracked/clean, integrity alerts,
      untracked, and quarantined).
    - Toggling the global 'Enforce' mode (automatic quarantine on alert).
    - Toggling the aggressive 'Block New' mode (immediate deletion of untracked plugins).
    - Triggering RPC actions via clickable links in the output, such as:
        - Approving/Snapshotting a new plugin.
        - Disapproving a tracked plugin (removing its baseline).
        - Manually quarantining a plugin.
        - Restoring a plugin from quarantine.
        - Permanently deleting a quarantined plugin.

    The panel uses an asynchronous queue and timer (`_update_timer`, `_update_queue`)
    to handle incoming status updates from the agent in a thread-safe, rate-limited manner,
    ensuring a smooth user experience.
    """

    cache_panel = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        ...
        self._update_queue = deque()
        self._update_lock = QMutex()
        self._update_timer = QTimer()
        self._update_timer.setInterval(50)          # 20 fps drain rate
        self._update_timer.timeout.connect(self._drain_updates)
        self._update_timer.start()
        self.setLayout(self._build_layout())
        self.auto_scroll = True
        self.output_box.setOpenExternalLinks(False)
        self.output_box.setTextInteractionFlags(
            self.output_box.textInteractionFlags() | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.output_box.anchorClicked.connect(self._handle_anchor)

    def _build_layout(self):
        try:
            layout = QVBoxLayout()
            title = QLabel("WordPress Plugin Guard")
            title.setStyleSheet("font-weight: bold; font-size: 16px;")
            layout.addWidget(title)

            # Buttons row
            btn_row = QHBoxLayout()

            self.show_status_btn = QPushButton("Show Status")

            #self.snapshot_btn = QPushButton("Snapshot Plugins")
            self.enforce_btn = QPushButton("Toggle Enforce")

            btn_row.addWidget(self.show_status_btn)
            #btn_row.addWidget(self.snapshot_btn)
            btn_row.addWidget(self.enforce_btn)

            #self.snapshot_btn.clicked.connect(self._snapshot_plugins)
            self.enforce_btn.clicked.connect(self._toggle_enforce)
            self.show_status_btn.clicked.connect(self._show_status)

            layout.addLayout(btn_row)

            self.block_btn = QPushButton("Block New")
            self.block_btn.setCheckable(True)
            self.block_btn.clicked.connect(self._toggle_block)
            btn_row.addWidget(self.block_btn)

            # Output area
            self.output_box = QTextBrowser()
            self.output_box.setReadOnly(True)
            self.output_box.setStyleSheet("""
                * { font-family: Consolas, monospace; }
                h1, h2, h3, h4 { 
                    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; 
                    font-weight: bold;
                    letter-spacing: 0.5px;
                }
            """)
            layout.addWidget(self.output_box)

            return layout
        except Exception as e:
            emit_gui_exception_log("PluginGuard._build_layout", e)

    # --- Required abstract methods from PhoenixPanelInterface ---
    def _connect_signals(self):
        """Attach inbound signal for plugin guard updates."""
        try:
            scoped = "inbound.verified.plugin_guard.panel.update"
            self.bus.on(scoped, self._queue_output)
            print(f"[PLUGIN-GUARD] 🎧 Connected to {scoped}")
            # After connecting, immediately sync status once
            QTimer.singleShot(250, self._request_initial_status)
        except Exception as e:
            emit_gui_exception_log("PluginGuard._connect_signals", e)

    def _disconnect_signals(self):
        """Detach inbound signal and clear queued updates."""
        try:
            scoped = "inbound.verified.plugin_guard.panel.update"
            self.bus.off(scoped, self._queue_output)
            self._update_queue.clear()
            print(f"[PLUGIN-GUARD] 🔕 Disconnected from {scoped}")
        except Exception as e:
            emit_gui_exception_log("PluginGuard._disconnect_signals", e)

    def get_panel_buttons(self):
        """Return toolbar button for the Plugin Guard panel."""
        return [
            PanelButton("🧹", "Plugin Guard",
                        lambda: self.session_window.show_specialty_panel(self))
        ]

    def _on_show(self):
        """Optional hook for when the panel becomes visible."""
        # Immediately refresh button state and request status sync
        QTimer.singleShot(200, self._sync_button_states)
        print("[PLUGIN-GUARD] 🌐 Panel shown — refreshing status...")

    # === Button Actions ===
    def _show_plugins(self):
        self._send_service_request("plugin.guard.list_plugins",
                                   {"session_id": self.session_id, "return_handler": "plugin_guard.panel.update"})

        self._append_output("[ACTION] 📦 Listing installed plugins...")

    def _snapshot_plugins(self):
        reply = QMessageBox.question(
            self,
            "Confirm Snapshot",
            "Are you sure you want to snapshot all tracked plugins?\n\n"
            "This will approve their current state as the trusted baseline.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._append_output("[ACTION] ❌ Snapshot cancelled by user.")
            return

        self._send_service_request("plugin.guard.snapshot",
                                   {"session_id": self.session_id, "return_handler": "plugin_guard.panel.update"})
        self._append_output("[ACTION] 🔐 Snapshot plugins requested.")

    def _show_status(self):
        self._send_service_request("plugin.guard.status",
                                   {"session_id": self.session_id, "return_handler": "plugin_guard.panel.update"})
        self._append_output("[ACTION] 🔎 Checking plugin status...")

    def _show_trusted(self):
        self._send_service_request("plugin.guard.list_trusted", {"session_id": self.session_id,  "return_handler": "plugin_guard.panel.update"})
        self._append_output("[ACTION] 📜 Listing trusted plugins...")

    def _show_quarantined(self):
        self._send_service_request("plugin.guard.list_quarantined", {"session_id": self.session_id,  "return_handler": "plugin_guard.panel.update"})
        self._append_output("[ACTION] 🚨 Listing quarantined plugins...")

    def _generate_trust(self):
        try:
            self._send_service_request("plugin.guard.generate", {"session_id": self.session_id,  "return_handler": "plugin_guard.panel.update"})
            self._append_output("[ACTION] 🔐 Trust file regeneration requested.")
        except Exception as e:
            emit_gui_exception_log("PluginGuard._generate_trust", e)

    def _reload_trust(self):
        try:
            self._send_service_request("plugin.guard.reload", {"session_id": self.session_id, "return_handler": "plugin_guard.panel.update"})
            self._append_output("[ACTION] 🔄 Reload trusted plugins command sent.")
        except Exception as e:
            emit_gui_exception_log("PluginGuard._reload_trust", e)

    def _toggle_enforce(self):
        try:
            self._append_output("[ACTION] ⚔️ Enforcement toggle requested.")
            self._send_service_request(
                "plugin.guard.enforce",
                {
                    # don’t send True/False here — let agent flip its own flag
                    "session_id": self.session_id,
                    "return_handler": "plugin_guard.panel.update",
                },
            )
        except Exception as e:
            emit_gui_exception_log("PluginGuard._toggle_enforce", e)


    def _toggle_block(self):
        try:
            enable = self.block_btn.isChecked()

            if enable:
                # 🔥 warn before sending the nuke
                reply = QMessageBox.warning(
                    self,
                    "Confirm Block-New Mode",
                    (
                        "⚠️  Block-New mode will *immediately delete* any untracked plugin folders "
                        "on the next scan.\n\n"
                        "If there's anything in your plugins directory that isn't approved, "
                        "it's getting firebombed.\n\n"
                        "Are you absolutely sure you want to arm it?"
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    # revert toggle visually
                    self.block_btn.setChecked(False)
                    self.block_btn.setStyleSheet("")
                    self._append_output("[ACTION] 🧱 Block-New arm cancelled by user.")
                    return

            state_text = "enabled" if enable else "disabled"
            self._append_output(f"[ACTION] 🧱 Block-New mode {state_text}.")
            self._send_service_request(
                "plugin.guard.block",
                {
                    "block_new": enable,
                    "session_id": self.session_id,
                    "return_handler": "plugin_guard.panel.update",
                },
            )

            if enable:
                self.block_btn.setStyleSheet("background-color:#dc3545;color:white;")  # red: armed
            else:
                self.block_btn.setStyleSheet("")

        except Exception as e:
            emit_gui_exception_log("PluginGuard._toggle_block", e)

    def _sync_button_states(self):
        """ask the agent for its current block/enforce states and update buttons"""
        try:
            self._send_service_request(
                "plugin.guard.status",
                {"session_id": self.session_id, "return_handler": "plugin_guard.panel.update"}
            )
        except Exception as e:
            emit_gui_exception_log("PluginGuard._sync_button_states", e)

    def _handle_sync_state(self, session_id, channel, source, payload, **_):
        try:
            data = payload.get("content", {})
            # the agent already includes enforce_state / block_new in payload
            block_state = data.get("block_new", False)
            enforce_state = data.get("enforce_state", False)

            self.block_btn.setChecked(block_state)
            if block_state:
                self.block_btn.setStyleSheet("background-color:#dc3545;color:white;")
            else:
                self.block_btn.setStyleSheet("")

            # add a matching enforce button color cue if you want
            if enforce_state:
                self.enforce_btn.setStyleSheet("background-color:#ffc107;color:black;")
            else:
                self.enforce_btn.setStyleSheet("")

            self._append_output(f"[INIT] 🧱 Block-New: {block_state} | ⚔️ Enforce: {enforce_state}")
        except Exception as e:
            emit_gui_exception_log("PluginGuard._handle_sync_state", e)

    # === Core Send Helper ===
    def _send_service_request(self, service, payload):
        pk = Packet()
        pk.set_data({
            "handler": "cmd_service_request",
            "ts": time.time(),
            "content": {
                "service": service,
                "payload": payload,
                "token": str(uuid.uuid4()),
            }
        })
        self.bus.emit("outbound.message", session_id=self.session_id,
                      channel="outgoing.command", packet=pk)

    def _queue_output(self, session_id, channel, source, payload, **_):
        self._update_lock.lock()
        self._update_queue.append((session_id, channel, source, payload))
        self._update_lock.unlock()

    def _drain_updates(self):
        if not self._update_queue:
            return
        self._update_lock.lock()
        item = self._update_queue.popleft()
        self._update_lock.unlock()

        try:
            self._safe_handle_output(*item)
        except Exception as e:
            emit_gui_exception_log("PluginGuard._drain_updates", e)

    def _append_output(self, text):
        self.output_box.append(text)
        if self.auto_scroll:
            self.output_box.moveCursor(QTextCursor.MoveOperation.End)

    def _approve_plugin(self, plugin):
        self._append_output(f"[DEBUG] Sending approve RPC for {plugin}")
        self._send_service_request("plugin.guard.snapshot_plugin",
                                   {"plugin": plugin,
                                    "session_id": self.session_id,
                                    "return_handler": "plugin_guard.panel.update"})

    def _disapprove_plugin(self, plugin, manual_quarantine=False):
        self._append_output(f"[ACTION] ❌ Disapprove requested for {plugin}")
        self._send_service_request(
            "plugin.guard.disapprove_plugin",
            {
                "plugin": plugin,
                "manual_quarantine": manual_quarantine,
                "session_id": self.session_id,
                "return_handler": "plugin_guard.panel.update",
            },
        )

    def _request_initial_status(self):
        """ask agent for full plugin status on first connect"""
        try:
            self._append_output("[INIT] 🔎 Requesting initial Plugin Guard status...")
            self._send_service_request(
                "plugin.guard.status",
                {"session_id": self.session_id, "return_handler": "plugin_guard.panel.update"}
            )
        except Exception as e:
            emit_gui_exception_log("PluginGuard._request_initial_status", e)

    def _handle_anchor(self, url: QUrl):
        href = url.toString()
        if href.startswith("approve:"):
            plugin = href.split(":", 1)[1]
            self._approve_plugin(plugin)
        elif href.startswith("disapprove:"):
            plugin = href.split(":", 1)[1]
            self._disapprove_plugin(plugin)
        elif href.startswith("restore:"):
            plugin = href.split(":", 1)[1]
            self._restore_plugin(plugin)
        elif href.startswith("reapprove:"):
            plugin = href.split(":", 1)[1]
            self._reapprove_plugin(plugin)
        elif href.startswith("deleteq:"):
            plugin = href.split(":", 1)[1]
            self._append_output(f"[ACTION] 💀 Delete requested for {plugin}")
            self._send_service_request(
                "plugin.guard.delete_quarantined",
                {
                    "plugin": plugin,
                    "session_id": self.session_id,
                    "return_handler": "plugin_guard.panel.update",
                },
            )
        elif href.startswith("quarantine:"):
            plugin = href.split(":", 1)[1]
            self._append_output(f"[DEBUG] Sending quarantine RPC for {plugin}")
            self._send_service_request(
                "plugin.guard.quarantine",
                {
                    "plugin": plugin,
                    "session_id": self.session_id,
                    "return_handler": "plugin_guard.panel.update",
                },
            )


    def _restore_plugin(self, plugin):
        self._append_output(f"[DEBUG] Sending restore RPC for {plugin}")
        self._send_service_request("plugin.guard.restore_plugin",
                                   {"plugin": plugin,
                                    "session_id": self.session_id,
                                    "return_handler": "plugin_guard.panel.update"})

    def _append_plugin_entry(self, plugin, approve=False, disapprove=False, restore=False, reapprove=False, quarantine=False, deleteq=False):

        try:
            html = f"<p><b>• {plugin}</b>"
            if approve:
                html += f" &nbsp;&nbsp;<a href='approve:{plugin}' style='color:#155724;text-decoration:none;background:#d4edda;padding:2px 6px;border-radius:3px;'>Approve</a>"
            if disapprove:
                html += f" &nbsp;&nbsp;<a href='disapprove:{plugin}' style='color:#721c24;text-decoration:none;background:#f8d7da;padding:2px 6px;border-radius:3px;'>Disapprove</a>"
            if restore:
                html += f" &nbsp;&nbsp;<a href='restore:{plugin}' style='color:#004085;text-decoration:none;background:#cce5ff;padding:2px 6px;border-radius:3px;'>Restore</a>"
            if reapprove:
                html += f" &nbsp;&nbsp;<a href='reapprove:{plugin}' style='color:#155724;text-decoration:none;background:#d4edda;padding:2px 6px;border-radius:3px;'>Mark Clean</a>"
            if quarantine:
                html += f" &nbsp;&nbsp;<a href='quarantine:{plugin}' style='color:#721c24;text-decoration:none;background:#f8d7da;padding:2px 6px;border-radius:3px;'>Quarantine</a>"
            if deleteq:
                html += f" &nbsp;&nbsp;<a href='deleteq:{plugin}' style='color:white;background:#000;padding:2px 6px;border-radius:3px;'>Delete</a>"
            html += "</p><hr>"
            self.output_box.insertHtml(html)
            if self.auto_scroll:
                self.output_box.moveCursor(QTextCursor.MoveOperation.End)

        except Exception as e:
            emit_gui_exception_log("PluginGuard._append_plugin_entry", e)

    def _reapprove_plugin(self, plugin):
        self._append_output(f"[DEBUG] Resnapshotting trusted baseline for {plugin}")
        self._send_service_request(
            "plugin.guard.snapshot_plugin",
            {
                "plugin": plugin,
                "session_id": self.session_id,
                "return_handler": "plugin_guard.panel.update"
            },
        )


    def _safe_handle_output(self, session_id, channel, source, payload, **_):
        try:
            data = payload.get("content", {})
            block_state = data.get("block_new")
            enforce_state = data.get("enforce_state")

            if block_state is not None:
                self.block_btn.setChecked(block_state)
                self.block_btn.setStyleSheet("background-color:#dc3545;color:white;" if block_state else "")

            if enforce_state is not None:
                self.enforce_btn.setStyleSheet("background-color:#ffc107;color:black;" if enforce_state else "")

            # clear safely
            self.output_box.blockSignals(True)
            self.output_box.clear()
            self.output_box.blockSignals(False)

            # helper
            def header(title, note=""):
                html = (
                    f"<div style='margin-top:12px;margin-bottom:6px;'>"
                    f"<h3 style='margin:0;padding:0;'>{title}</h3>"
                )
                if note:
                    html += f"<div style='color:#666;font-style:italic;margin:2px 0 6px 0;'>{note}</div>"
                html += "</div>"
                self.output_box.insertHtml(html)

            self.output_box.insertHtml("""
                <div style='margin-bottom:10px;'>
                    <h2 style='margin:0;padding:0;'>🧹 Plugin Guard Status</h2>
                    <hr style='margin:4px 0 8px 0;' />
                </div>
            """)

            # ✅ Tracked & Clean
            header("✅ Tracked & Clean", "These are plugins you’ve marked as trusted.")
            clean = data.get("tracked_clean", [])
            if clean:
                for p in clean:
                    self._append_plugin_entry(p, disapprove=True)
            else:
                self.output_box.insertHtml("<p>No trusted plugins yet.</p><br />")

            # 👽 Untracked
            header("👽 Untracked Plugins", "New folders found. You can approve or quarantine them.")
            untracked = data.get("untracked", [])
            if untracked:
                for p in untracked:
                    self._append_plugin_entry(p, approve=True, quarantine=True)
            else:
                self.output_box.insertHtml("<p>No new or unknown plugins detected.</p><br />")

            # 🚫 Quarantined
            header("🚫 Quarantined Plugins", "These were moved aside for safety.")
            quarantined = data.get("quarantined_plugins", [])
            if quarantined:
                for p in quarantined:
                    self._append_plugin_entry(p, restore=True, deleteq=True)
            else:
                self.output_box.insertHtml("<p>No quarantined plugins at this time.</p><br />")

            # 🚨 Integrity Alerts
            header("🚨 Integrity Alerts", "Plugins that changed since last approval.")
            alerts = data.get("tracked_alerts", {})
            if alerts:
                for plugin, info in alerts.items():
                    reason = info.get("reason", "Unknown change")
                    # show the reason plus action buttons
                    self.output_box.insertHtml(
                        f"<p>• <b>{plugin}</b> – {reason}</p>"
                    )
                    # add actionable options
                    self._append_plugin_entry(
                        plugin,
                        reapprove=True,  # Mark Clean
                        quarantine=True  # Quarantine
                    )
            else:
                self.output_box.insertHtml("<p>All trusted plugins are stable.</p><br />")

            self.output_box.moveCursor(QTextCursor.MoveOperation.End)


            def _refresh_view():
                self.output_box.viewport().update()
                self.output_box.updateGeometry()
                self.output_box.repaint()


            QTimer.singleShot(0, _refresh_view)

        except Exception as e:
            emit_gui_exception_log("PluginGuard._handle_output", e)
