# Authored by Daniel F MacDonald and ChatGPT aka The Generals
import sys
import time
import datetime
import copy
from PyQt5.QtWidgets import QApplication, QMainWindow, QTextEdit

from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QSplitter,  QVBoxLayout, QHBoxLayout, QToolBar,
    QGroupBox, QSizePolicy, QLabel, QPushButton, QApplication, QAction
)
from matrix_gui.core.panel.agent_detail.agent_detail_panel import AgentDetailPanel
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.core.panel.log_panel.log_panel import LogPanel
from matrix_gui.core.panel.agent_tree.agent_tree import PhoenixAgentTree
from matrix_gui.modules.net.deployment_connector import _connect_single
from matrix_gui.core.dispatcher.inbound_dispatcher import InboundDispatcher
from matrix_gui.core.dispatcher.outbound_dispatcher import OutboundDispatcher
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.dialog.replace_agent_dialog import ReplaceAgentDialog

def run_session(session_id, conn):

    try:
        msg = conn.recv()

        #deep copy, encase the vault is updated, you don't want to corrupt the vault data with
        # session data, updated node
        deployment = copy.deepcopy(msg.get("deployment"))

        # Create SessionContext + Bus wiring through deployment_connector
        ctx = _connect_single(deployment, deployment.get("id"))

        # Launch dispatchers (tied to ctx.bus)
        inbound = InboundDispatcher(ctx.bus)
        outbound = OutboundDispatcher(ctx.bus, get_sessions(), deployment)
        ctx.inbound, ctx.outbound = inbound, outbound

        # GUI launch
        app = QApplication(sys.argv)
        win = SessionWindow(
            session_id=ctx.id,
            deployment=deployment,
            conn=conn,
            bus=ctx.bus,
            inbound=inbound,
            outbound=outbound
        )
        win.show()
        app.exec_()

        # GUI
        app = QApplication(sys.argv)
        win = SessionWindow(session_id, deployment, conn, ctx.bus, inbound, outbound)
        win.setWindowTitle("Matrix")
        win.show()
        app.exec_()

    except Exception as e:
        emit_gui_exception_log("session_window.run_session", e)

class SessionWindow(QMainWindow):
    def __init__(self, session_id, deployment, conn, bus, inbound, outbound):
        super().__init__()
        try:
            self.conn = conn
            self.session_id = session_id
            self.deployment = deployment
            self.bus = bus
            self.inbound = inbound
            self.outbound = outbound

            self.active_log_token = None
            self.log_paused = False
            self.last_log_ts = None
            self.current_log_title = ""

            self.resize(1000, 700)
            self.setMinimumHeight(650)

            # Panels
            self.tree_wrapper = self._build_tree_panel()
            self.inspector_wrapper = self._build_inspector_panel()
            self.console_wrapper = self._build_log_panel()

            # Status bar
            self.status_label = QLabel("Status: Initializing...")
            self._setup_status_bar()

            # Layout
            main_widget = QWidget()
            main_layout = QHBoxLayout()
            main_widget.setLayout(main_layout)
            self.setCentralWidget(main_widget)
            self._setup_main_layout(main_layout)

            # Controls
            self._make_controls()

            self.log_view.line_count_changed.connect(self._on_log_count_changed)

            # Events

            self.bus.on("channel.status", self._handle_channel_status)
            self.bus.on(f"inbound.verified.agent_log_view.update.{self.session_id}", self._handle_log_update)
            self.bus.on("gui.log.token.updated", self._set_active_log_token)

        except Exception as e:
            emit_gui_exception_log("session_window.__init__", e)

    def _set_active_log_token(self, session_id, token, agent_title=None, **_):
        self.active_log_token = token
        self.current_log_title = agent_title or "Unknown"
        self.log_view.set_active_token(token)  # reset log panel
        self._update_log_status_bar()

    def _handle_channel_status(self, session_id, channel, status, info=None, **_):
        try:
            msg = f"{channel}: {status}"
            self.status_label.setText(f"Status: {msg}")
        except Exception as e:
            emit_gui_exception_log("session_window._handle_channel_status", e)

    # --- Builders ---
    def _build_tree_panel(self):
        box = QGroupBox("🧠 Agent Tree")
        box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                padding: 4px;
                margin: 2px;
                border: 1px solid #888;
                border-radius: 4px;
            }
        """)
        layout = QVBoxLayout()
        self.tree = PhoenixAgentTree(session_id=self.session_id, bus=self.bus, parent=self)
        layout.addWidget(self.tree)
        box.setLayout(layout)
        return box

    def _build_inspector_panel(self):
        self.detail_panel = AgentDetailPanel(session_id=self.session_id, bus=self.bus)
        self.detail_panel.inspector_group.setVisible(False)
        self.detail_panel.config_group.setVisible(False)
        return self.detail_panel


    def _build_log_panel(self):
        box = QGroupBox("📄 Agent Logs")
        box.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                padding: 4px;
                margin: 2px;
                border: 1px solid #888;
                border-radius: 4px;
            }
        """)
        layout = QVBoxLayout()

        # Status line inside the box
        self.log_status_label = QLabel("Agent Logs: —")
        self.log_status_label.setStyleSheet("padding: 2px;")
        layout.addWidget(self.log_status_label)

        # The actual log view
        self.log_view = LogPanel(self.bus, self)
        self.log_view.line_count_changed.connect(self._on_log_count_changed)
        layout.addWidget(self.log_view)

        box.setLayout(layout)
        return box

    def _setup_main_layout(self, main_layout):
        right_column = QVBoxLayout()
        right_column.addWidget(self.detail_panel.inspector_group)
        right_column.addWidget(self.detail_panel.config_group)
        right_column.addWidget(self.console_wrapper)

        right_panel = QWidget()
        right_panel.setLayout(right_column)

        main_layout.addWidget(self.tree_wrapper)
        main_layout.addWidget(right_panel)
        main_layout.setStretch(0, 1)
        main_layout.setStretch(1, 3)

    # --- Controls ---
    def _make_controls(self):
        bar = QToolBar("Deployment Controls", self)
        self.addToolBar(Qt.TopToolBarArea, bar)

        # Kill
        kill_act = QAction("☠️ Kill", self)
        kill_act.triggered.connect(lambda: self._send_cmd("kill"))
        bar.addAction(kill_act)

        # Replace Source
        replace_src_act = QAction("♻️ Replace Source", self)
        replace_src_act.triggered.connect(self.launch_replace_agent_modal)
        bar.addAction(replace_src_act)

        # Restart Agent
        restart_act = QAction("🔁 Restart Agent", self)
        restart_act.setToolTip("Restart this agent after replacing its source.")
        restart_act.triggered.connect(lambda: self._send_cmd("restart"))
        bar.addAction(restart_act)

        # Threads toggle
        self.toggle_threads = QAction("🧵 Threads", self)
        self.toggle_threads.setCheckable(True)
        self.toggle_threads.setToolTip("Threads & Processes")
        self.toggle_threads.triggered.connect(
            lambda checked: self.detail_panel.inspector_group.setVisible(checked)
        )
        bar.addAction(self.toggle_threads)

        # Config toggle
        self.toggle_config = QAction("⚙️ Config", self)
        self.toggle_config.setCheckable(True)
        self.toggle_config.triggered.connect(
            lambda checked: self.detail_panel.config_group.setVisible(checked)
        )
        bar.addAction(self.toggle_config)

        # Pause Logs
        self.pause_btn = QAction("⏸️ Pause Logs", self)
        self.pause_btn.setCheckable(True)
        self.pause_btn.triggered.connect(self._toggle_log_pause)
        bar.addAction(self.pause_btn)


    # --- Log Update ---
    def _handle_log_update(self, session_id, channel, source, payload, **_):
        content = payload.get("content", {})
        token = content.get("token")
        lines = content.get("lines", [])


        if not lines:
            return

        # Token check
        if token != self.log_view.get_active_token():
            return

        if not self.log_paused:
            self.log_view.append_log_lines(lines)
            self.last_log_ts = time.time()

        self._update_log_status_bar()

    def _replace_agent_source(self):
        pass

    def _on_log_count_changed(self, count: int):
        self._last_log_count = count
        self._update_log_status_bar()

    def _toggle_log_pause(self):
        """Toggle paused state of log updates."""
        self.log_paused = self.pause_btn.isChecked()
        self._update_log_status_bar()

    def launch_replace_agent_modal(self):
        dlg = ReplaceAgentDialog(session_id=self.session_id, bus=self.bus, parent=self)
        dlg.exec_()

    def _update_log_status_bar(self):
        try:
            time_str = (
                datetime.datetime.fromtimestamp(self.last_log_ts).strftime("%H:%M:%S")
                if self.last_log_ts else "—"
            )
            mode = "⏸️ Paused" if self.log_paused else "📡 Live"
            label = self.current_log_title or "Unknown"

            # Show log status on the inside label (not the border)
            count = getattr(self, "_last_log_count", 0)
            self.log_status_label.setText(
                f"Agent Logs: {label} ({mode} at {time_str} – {count} lines)"
            )

        except Exception as e:
            emit_gui_exception_log("session_window._update_log_status_bar", e)

    # --- Other unchanged methods ---
    def _send_cmd(self, cmd): pass
    def _setup_status_bar(self):
        status_bar = QToolBar("Session Status", self)
        status_bar.setMovable(False)
        status_bar.addWidget(self.status_label)
        self.addToolBar(Qt.BottomToolBarArea, status_bar)

    def closeEvent(self, ev):
        try:
            print(f"[SESSION] Window for {self.session_id} closing, notifying cockpit...")
            if self.conn:
                try:
                    self.conn.send({
                        "type": "exit",
                        "session_id": self.session_id
                    })
                except Exception as e:
                    print(f"[SESSION][WARN] Could not notify cockpit: {e}")
        except Exception as e:
            emit_gui_exception_log("SessionWindow.closeEvent", e)
        finally:
            super().closeEvent(ev)