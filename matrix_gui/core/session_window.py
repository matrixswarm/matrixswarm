# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import sys
import time
import datetime
from pathlib import Path
import inspect
import copy
from PyQt6 import QtWidgets
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QSize, QTimer, QMetaObject, Qt, Q_ARG, pyqtSlot
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolBar,
    QGroupBox, QApplication, QMainWindow, QStackedWidget, QLabel, QMessageBox
)
from matrix_gui.core.panel.control_bar import PanelButton
from matrix_gui.core.panel.agent_detail.agent_detail_panel import AgentDetailPanel
from matrix_gui.core.panel.crypto_alert.crypto_alert import CryptoAlertPanel
from matrix_gui.core.panel.delete_agent_panel import DeleteAgentPanel
from matrix_gui.theme.utils.hive_ui import StatusLabel
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.core.panel.log_panel.log_panel import LogPanel
from matrix_gui.core.panel.agent_tree.agent_tree import PhoenixAgentTree
from matrix_gui.modules.net.deployment_connector import _connect_single
from matrix_gui.core.dispatcher.inbound_dispatcher import InboundDispatcher
from matrix_gui.core.dispatcher.outbound_dispatcher import OutboundDispatcher
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.connector_bus import ConnectorBus
from matrix_gui.core.panel.restart_agent_panel import RestartAgentPanel
from matrix_gui.core.panel.replace_agent_panel import ReplaceAgentPanel
from matrix_gui.core.panel.hotswap_agent_panel import HotswapAgentPanel
from matrix_gui.core.panel.inject_agent_panel import InjectAgentPanel
from matrix_gui.core.panel.multiplexer_panel import MultiplexerPanel
from matrix_gui.core.panel.control_bar import ControlBar
from matrix_gui.modules.vault.services.vault_connection_singleton import VaultConnectionSingleton
from matrix_gui.core.class_lib.packet_delivery.packet.standard.command.packet import Packet
from matrix_gui.modules.directive.deploy_dialog import DeployDialog

def run_session(session_id, conn):
    """
    Executes a session, initializing its configurations, inter-process communication, and monitoring tools.

    @param str session_id: Unique identifier for the session.
    @param multiprocessing.Connection conn: IPC connection for communication with the parent process.

    @return None
    """

    app = QApplication.instance() or QApplication(sys.argv)

    # --- Dynamically locate and load the global Hive theme ---
    try:

        # Find the directory where this file (session_window.py) lives
        current_file = Path(inspect.getfile(inspect.currentframe())).resolve()

        # Walk upward until we hit the "matrix_gui" folder, then add /theme/hive_theme.qss
        for parent in current_file.parents:
            if parent.name == "matrix_gui":
                theme_path = parent / "theme" / "hive_theme.qss"
                break
        else:
            theme_path = Path.cwd() / "matrix_gui" / "theme" / "hive_theme.qss"

        if theme_path.exists():
            with open(theme_path, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
            print(f"[SESSION][INFO] Loaded theme dynamically from {theme_path}")
        else:
            print(f"[SESSION][WARN] Theme file not found at {theme_path}")

    except Exception as e:
        emit_gui_exception_log("[SESSION][ERROR] Failed to load theme dynamically:", e)

    try:

        msg = conn.recv()
        deployment = copy.deepcopy(msg.get("deployment"))

        # --- Preflight validation: require ingress + egress ---
        try:
            agents = deployment.get("agents", [])
            missing = []

            has_outgoing = False
            has_incoming = False

            for agent in agents:
                channel = (agent.get("connection", {}).get("channel") or "").strip().lower()

                if channel == "outgoing.command":
                    has_outgoing = True

                elif channel == "payload.reception":
                    has_incoming = True

            if not has_outgoing:
                missing.append("need at least one agent with outgoing.command capability")

            if not has_incoming:
                missing.append("need at least one agent with payload.reception capability")

            if missing:

                msg_text = (
                    "Phoenix requires at least one ingress and one egress agent to connect.\n\n"
                    "Missing:\n - " + "\n - ".join(missing) +
                    "\n\nAdd them to your directive before launching this session."
                )
                box = QMessageBox(QMessageBox.Icon.Critical,
                                  "Missing Core Agents",
                                  msg_text,
                                  parent=app.activeWindow())
                box.setWindowModality(Qt.WindowModality.ApplicationModal)
                box.exec()
                print(f"[SESSION][ABORT] Deployment missing core agents: {missing}")
                return
            else:
                print("[SESSION][CHECK] ✅ Ingress/Egress agents detected.")
        except Exception as e:
            emit_gui_exception_log(f"[SESSION][WARN] Preflight check failed", e)

        ctx = _connect_single(deployment, session_id, deployment.get("id"))
        inbound = InboundDispatcher(ctx.bus, session_id)
        outbound = OutboundDispatcher(ctx.bus, session_id)
        ctx.inbound, ctx.outbound = inbound, outbound

        print(f"[DEBUG] Bus ID for session {session_id}: {id(ctx.bus)}")

        win = SessionWindow(
            deployment_id=deployment.get("id"),
            session_id=ctx.id,
            cockpit_id=session_id,
            deployment=deployment,
            conn=conn,
            bus=ctx.bus,
            inbound=inbound,
            outbound=outbound,
            ctx=ctx
        )

        win.start_pipe_timer()

        # make window embeddable and not auto-activate
        win.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow)
        win.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        win.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        win.create()  # physically create the native handle without showing yet
        wid = int(win.winId())
        conn.send({"type": "window_ready", "session_id": session_id, "win_id": wid})
        win.show()


        try:
            app.exec()
        except Exception as e:
            import traceback
            emit_gui_exception_log("[SESSION][FATAL] Exception in session loop", e)
        finally:
            try:
                conn.send({"type": "exit", "session_id": session_id})
            except Exception as inner:
                print(f"[SESSION][FATAL] Failed to signal exit: {inner}")


    except Exception as e:
        emit_gui_exception_log("session_window.run_session", e)


class SessionWindow(QMainWindow):
    """
    Main window class for a Phoenix session, managing the UI layout, agent tree, logs, and dispatchers.

    @extends QMainWindow
    """

    def __init__(self, deployment_id, session_id, cockpit_id, deployment, conn, bus, inbound, outbound, ctx):
        """
        Initializes the SessionWindow with all necessary backend and frontend components.

        @param str deployment_id: The ID of the deployment.
        @param str session_id: The unique ID of this session.
        @param str cockpit_id: The cockpit's internal session ID.
        @param dict deployment: Deployment configuration data.
        @param multiprocessing.Connection conn: IPC connection.
        @param ConnectorBus bus: Event bus for internal communication.
        @param InboundDispatcher inbound: Dispatcher for incoming messages.
        @param OutboundDispatcher outbound: Dispatcher for outgoing commands.
        @param SessionContext ctx: The session context object.
        """
        super().__init__()
        try:

            self.deployment_id=deployment_id
            self.deployment = deployment
            #heartbeat timer
            self._hb_timer = QTimer(self)
            self._hb_timer.timeout.connect(self._send_heartbeat)
            self._hb_timer.start(2000)  # every 2 seconds

            #showing status bar
            self._blink_in_progress = False

            self.conn = conn
            self.session_id = session_id
            self.vault_singleton = VaultConnectionSingleton.get(dep_id=deployment_id, conn=conn)
            self.vault_singleton.load(deployment)

            self.cockpit_id = cockpit_id
            self.deployment = deployment
            self.bus = bus
            self.inbound_dispatcher = inbound
            self.outbound_dispatcher = outbound
            self.preferred_incoming_uid = None
            self.ctx = ctx
            self._panel_cache = {}

            self.active_log_token = None
            self.log_paused = False
            self.last_log_ts = None
            self.current_log_title = ""

            # refs to Panels
            self._restart_agent_panel=None
            self._replace_panel=None
            self._hotswap_panel=None
            self._inject_panel = None
            self._delete_agent_panel=None

            self.resize(1000, 700)
            self.setMinimumHeight(650)

            # Panels
            self.tree_wrapper = self._build_tree_panel()
            self.inspector_wrapper = self._build_inspector_panel()
            self.console_wrapper = self._build_log_panel()
            self.console_wrapper.setObjectName("logs")

            # Status bar
            self.status_label = QLabel("")  # keep object but empty & hidden
            self.status_label.hide()

            # Window Icon
            logo_path = "matrix_gui/theme/panel_logo.png"
            self.setWindowIcon(QIcon(logo_path))

            # Build the default cockpit panel (tree + inspector + logs)
            self.default_panel = QWidget()
            default_layout = QHBoxLayout()
            self.default_panel.setLayout(default_layout)
            self._setup_main_layout(default_layout)  # reuses existing builder
            default_layout.setContentsMargins(0, 0, 0, 0)
            default_layout.setSpacing(0)

            # Stacked widget for extensibility
            self.stacked = QStackedWidget()
            self.stacked.addWidget(self.default_panel)  # index 0 = default cockpit view
            self.setCentralWidget(self.stacked)

            # Control Bar
            self.control_bar = ControlBar(self)
            self.setIconSize(QSize(24, 24))
            self.setMinimumHeight(36)

            self._setup_status_bar()

            #multiplexor setup
            self.outgoing_connectors = {}
            default_found = False
            ## EGRESS AGENT
            for a in deployment.get("agents", []):
                ch = a.get("connection", {}).get("channel")
                if ch == "outgoing.command":
                    uid = a.get("universal_id")
                    self.outgoing_connectors[uid] = a

                    # if this one is marked default, assign it as the active connector
                    if a.get("connection", {}).get("default_outgoing"):
                        self.outbound_dispatcher.set_outbound_connector(a)
                        self.outgoing_badge.setText(f"Outgoing: {uid}  ⚪")
                        default_found = True

            # fallback: if no default marked, just pick the first one
            if not default_found and self.outgoing_connectors:
                first_uid, first_agent = next(iter(self.outgoing_connectors.items()))
                self.outbound_dispatcher.set_outbound_connector(first_agent)
                self.outgoing_badge.setText(f"Outgoing: {first_uid}  ⚪")

            try:
                incoming_candidate = None
                incoming_agents = []

                # collect all payload.reception agents in deployment order
                for a in deployment.get("agents", []):
                    ch = (a.get("connection", {}).get("channel") or "").strip().lower()
                    if ch == "payload.reception":
                        incoming_agents.append(a)

                # Match deployment boot policy: first flagged default wins.
                for a in incoming_agents:
                    conn = a.get("connection", {}) or {}
                    if bool(conn.get("default_payload_reception", False)):
                        incoming_candidate = a
                        break

                # fallback: websocket if no explicit default set
                if not incoming_candidate:
                    for a in incoming_agents:
                        name = (a.get("name") or "").strip().lower()
                        proto = (a.get("connection", {}).get("proto") or "").strip().lower()
                        if proto == "wss" or "websocket" in name:
                            incoming_candidate = a
                            break

                # final fallback: first payload.reception connector
                if not incoming_candidate and incoming_agents:
                    incoming_candidate = incoming_agents[0]

                if incoming_candidate:
                    uid = incoming_candidate.get("universal_id")
                    self.preferred_incoming_uid = uid
                    self.inbound_dispatcher.set_inbound_connector(incoming_candidate)
                    self.incoming_badge.setText(f"Incoming: {uid}  ⚪")

            except Exception as e:
                print("[INIT_BADGES_ERROR]", e)

            self.log_view.line_count_changed.connect(self._on_log_count_changed)

            #session window title
            label = self.deployment.get("label", "unknown")
            self.setWindowTitle(f"Matrix | deployment: {label} | session-id: {self.session_id}")

            # Events
            self.bus.on("channel.packet.sent", self._handle_packet_sent)
            self.bus.on(f"inbound.verified.swarm_feed.alert", self._handle_swarm_alert)
            self.bus.on("channel.status", self._handle_channel_status)
            self.bus.on(f"inbound.verified.agent_log_view.update", self._handle_log_update)
            self.bus.on("gui.agent.selected", self._handle_agent_selected)
            self.bus.on("gui.log.token.updated", self._set_active_log_token)

        except Exception as e:
            emit_gui_exception_log("session_window.__init__", e)

    def start_pipe_timer(self):
        """
        Starts the timer that polls the IPC connection for external messages.
        """
        self._pipe_timer = QTimer(self)
        self._pipe_timer.timeout.connect(self._poll_conn)
        self._pipe_timer.start(200)

    def _poll_conn(self):
        """
        Polls the IPC connection for incoming messages, such as force close signals.
        @private
        """
        if not self.conn:
            return
        try:
            while self.conn.poll():
                msg = self.conn.recv()
                mtype = msg.get("type")
                if mtype == "force_close":
                    print(f"[SESSION] 🧨 Received external close for {self.session_id}")
                    self._handle_external_close()

        except (EOFError, OSError):
            print(f"[SESSION][PIPE] Lost pipe for {self.session_id}")
            self._pipe_timer.stop()

    def _send_heartbeat(self):
        """
        Sends a periodic heartbeat signal back to the parent process.
        @private
        """
        try:
            if self.conn:
                self.conn.send({"type": "heartbeat", "session_id": self.cockpit_id})
        except (BrokenPipeError, OSError):
            print("[SESSION][HEARTBEAT] Pipe lost; shutting down session.")
            self._hb_timer.stop()
            return

    def _set_active_log_token(self, session_id, token, agent_title=None, **_):
        """
        Sets the active log token to filter and display logs for a specific agent.

        @param str session_id: The session ID.
        @param str token: The log token to follow.
        @param str|None agent_title: The human-readable title of the agent.
        @private
        """
        try:
            self.active_log_token = token
            self.current_log_title = agent_title or "Unknown"
            self.log_view.set_active_token(token)  # reset log panel
            self._update_log_status_bar()
        except Exception as e:
            emit_gui_exception_log("session_window._set_active_log_token", e)

    def _handle_channel_status(self, session_id, channel, status, info=None, **_):
        try:
            dot = self._status_to_dot(status)

            # Resolve channel -> agent config
            matched_agent = None
            for a in self.deployment.get("agents", []):
                if a.get("universal_id") == channel:
                    matched_agent = a
                    break

            if matched_agent:
                ch = (matched_agent.get("connection", {}).get("channel") or "").strip().lower()

                if ch == "payload.reception":
                    # only update the selected/preferred incoming transport
                    if not self.preferred_incoming_uid or channel == self.preferred_incoming_uid:
                        self.incoming_badge.setText(f"Incoming: {channel}  {dot}")


                elif ch == "outgoing.command":

                    # Only let the currently selected outgoing connector update the badge
                    try:
                        active = self.outbound_dispatcher.get_outbound_connection()
                    except Exception:
                        active = None

                    active_uid = active.get("universal_id") if isinstance(active, dict) else None
                    if active_uid and channel != active_uid:
                        return

        except Exception as e:
            emit_gui_exception_log("session_window._handle_channel_status", e)

    def _handle_packet_sent(self, start_end=1):
        """
        Triggers a UI blink update when a packet is sent.

        @param int start_end: 1 to start blink (green), 0 to reset (white).
        @private
        """
        QMetaObject.invokeMethod(
            self,
            "_handle_packet_sent_ui",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(int, start_end)
        )

    @pyqtSlot(int)
    def _handle_packet_sent_ui(self, start_end):
        """
        Updates the outgoing badge UI to reflect packet transmission status.

        @param int start_end: 1 for green indicator, 0 for white indicator.
        @private
        """
        try:
            # determine symbol
            dot = "🟢" if start_end else "⚪"

            # parse current text
            text = self.outgoing_badge.text().strip()

            # Force rebuild instead of partial replace — some Qt themes cache identical strings
            if "Outgoing:" in text:
                # Grab everything before the last emoji or fallback to plain base
                base = text.split("⚪")[0].split("🟢")[0].split("🟡")[0].split("🔴")[0].strip()
                new_text = f"{base} {dot}"
            else:
                new_text = f"Outgoing: — {dot}"

            # Force repaint by setting text and updating the widget
            self.outgoing_badge.setText(new_text)
            self.outgoing_badge.repaint()
            QApplication.processEvents()  # push immediate paint to UI thread

            # auto-revert to ⚪ after a short delay if we just flashed green
            if start_end == 1:
                QTimer.singleShot(400, lambda: self._handle_packet_sent(0))

        except Exception as e:
            emit_gui_exception_log(f"[BLINK][ERROR] packet.sent handler", e)

    def _reset_outgoing_badge(self, style):
        """
        Resets the style of the outgoing badge.

        @param str style: The CSS stylesheet to apply.
        @private
        """
        self.outgoing_badge.setStyleSheet(style)
        self._blink_in_progress = False

    def _status_to_dot(self, status):
        """
        Maps a status string to a colored emoji dot.

        @param str status: The status string.
        @return str: Emoji dot representing the status.
        @private
        """
        return {
            "connected": "🟢",
            "ready": "🟢",
            "connecting": "🟡",
            "disconnected": "🔴",
            "idle": "⚪"
        }.get(status, "⚪")

    # --- Builders ---
    def _build_tree_panel(self):
        """
        Constructs the agent tree panel.

        @return QGroupBox: The group box containing the agent tree.
        @private
        """
        try:
            box = QGroupBox("🦉 Agent Tree")
            layout = QVBoxLayout()
            layout.setContentsMargins(6, 4, 6, 4)  # (L, T, R, B)
            layout.setSpacing(4)
            deployment = copy.deepcopy(self.deployment)
            self.tree = PhoenixAgentTree(session_id=self.session_id, bus=self.bus, conn=self.conn, deployment=deployment, parent=self)
            layout.addWidget(self.tree)
            box.setLayout(layout)
            return box
        except Exception as e:
            emit_gui_exception_log("session_window._build_tree_panel", e)

    def _handle_agent_selected(self, session_id, node, panels=None, **_):
        """
        Handles agent selection in the tree, updating the control bar with custom panel buttons.

        @param str session_id: The session ID.
        @param dict node: The selected agent node data.
        @param list|None panels: List of custom panels available for this agent.
        @private
        """

        if not panels:
            # No specialty panels -> stay where you are
            return

        try:

            all_buttons = []

            for panel_name in panels:
                panel = self._load_custom_panel(panel_name, node)
                if panel and hasattr(panel, "get_panel_buttons"):
                    panel_buttons = panel.get_panel_buttons() or []
                    if panel_buttons:

                        print(f"[DEBUG] {panel_name} returned {len(panel_buttons)} buttons")
                        # Defer showing panel until its button is clicked
                        for btn in panel_buttons:
                            # wrap handler so it switches panel when clicked
                            def make_handler(real_handler, p=panel):
                                def _wrapped():
                                    if real_handler:
                                        real_handler()
                                    self.stacked.setCurrentWidget(p)

                                return _wrapped

                            all_buttons.append(PanelButton(btn.icon, btn.text, make_handler(btn.handler, panel)))
                else:
                    print(f"[DEBUG] {panel_name} has no usable buttons, ignoring")

            # Only update toolbar if we actually collected something
            if all_buttons:
                self.control_bar.clear_secondary_buttons()
                self.control_bar.add_secondary_buttons(all_buttons)
            else:
                self.control_bar.clear_secondary_buttons()

        except Exception as e:
            emit_gui_exception_log("SessionWindow._handle_agent_selected", e)
            return None

    def _load_custom_panel(self, panel_name, node):
        """
        Dynamically loads and initializes a custom panel class.

        @param str panel_name: The dot-separated path to the panel.
        @param dict node: The agent node for which the panel is loaded.
        @return QWidget|None: The initialized panel instance or None if loading fails.
        @private
        """

        try:

            cache_key = panel_name
            if cache_key in self._panel_cache:
                return self._panel_cache[cache_key]

            parts = panel_name.split(".")
            mod_leaf = parts[-1]  # e.g. "email_check"
            mod_path = ".".join(parts[:-1]) if len(parts) > 1 else parts[0]
            class_name = "".join(part.capitalize() for part in mod_leaf.split("_"))  # EmailCheck
            full_mod = f"matrix_gui.core.panel.custom_panels.{mod_path}.{mod_leaf}"

            try:
                mod = __import__(full_mod, fromlist=[class_name])
            except ModuleNotFoundError:
                print(f"[WARNING][UI] Custom panel '{panel_name}' not found — skipping.")
                return None

            PanelClass = getattr(mod, class_name)
            panel = PanelClass(session_id=self.session_id, bus=self.bus, node=node, session_window=self)

            if panel.is_cached():
                self._panel_cache[cache_key] = panel

            return panel

        except Exception as e:
            emit_gui_exception_log("SessionWindow._load_custom_panel", e)
            return None

    def _build_inspector_panel(self):
        """
        Constructs the agent inspector panel.

        @return AgentDetailPanel: The inspector panel instance.
        @private
        """

        try:
            self.detail_panel = AgentDetailPanel(session_id=self.session_id, bus=self.bus)
            self.detail_panel.inspector_group.setVisible(False)
            self.detail_panel.config_group.setVisible(False)
            return self.detail_panel
        except Exception as e:
            emit_gui_exception_log("session_window._build_inspector_panel", e)

    def show_default_panel(self):
        """
        Return to the main cockpit view without resetting the whole toolbar.
        """
        try:
            self.stacked.setCurrentWidget(self.default_panel)
            # Only clear the secondary rack — keep the default top row
            #if hasattr(self, "control_bar"):
                #self.control_bar.clear_secondary_buttons()
        except Exception as e:
            emit_gui_exception_log("SessionWindow.show_default_panel", e)

    def show_specialty_panel(self, panel: QWidget):
        """
        Switches the main view to a specialty panel and updates the control bar.

        @param QWidget panel: The panel to display.
        """

        try:
            if self.stacked.currentWidget() == panel:
                print("[DEBUG] Panel already active, skipping reset")
                return
            if self.stacked.indexOf(panel) == -1:
                self.stacked.addWidget(panel)
            self.stacked.setCurrentWidget(panel)

            self.control_bar.clear_secondary_buttons()

            if hasattr(panel, "get_panel_buttons"):
                buttons = panel.get_panel_buttons()
                for btn in buttons:
                    self.control_bar.add_secondary_buttons([btn])
            else:
                self.control_bar.hide_secondary_row()

            # Always keep the main rack visible
            self.control_bar.show_secondary_row()

            # Always add Home
            self.control_bar.add_prefix_button("🔙", "Main", self.show_default_panel)
            print("[DEBUG] Added Home button")
        except Exception as e:
            emit_gui_exception_log("session_window.show_specialty_panel", e)


    def _build_log_panel(self):
        """
        Constructs the agent logs panel.

        @return QGroupBox: The group box containing the log view.
        @private
        """

        try:
            box = QGroupBox("📄 Agent Logs")

            layout = QVBoxLayout()
            layout.setContentsMargins(6, 4, 6, 4)
            layout.setSpacing(4)

            # Status line inside the box
            self.log_status_label = StatusLabel("Agent Logs: —")
            layout.addWidget(self.log_status_label)

            # The actual log view
            self.log_view = LogPanel(self.bus, self)
            self.log_view.line_count_changed.connect(self._on_log_count_changed)
            layout.addWidget(self.log_view)

            box.setLayout(layout)
            return box
        except Exception as e:
            emit_gui_exception_log("session_window._build_log_panel", e)

    def _setup_main_layout(self, main_layout):
        """
        Sets up the default layout for the cockpit view (tree + details + logs).

        @param QLayout main_layout: The layout to populate.
        @private
        """
        try:
            right_column = QVBoxLayout()
            right_column.setContentsMargins(0, 0, 0, 0)
            right_column.setSpacing(0)
            right_column.addWidget(self.detail_panel.inspector_group)
            right_column.addWidget(self.detail_panel.config_group)
            right_column.addWidget(self.console_wrapper)

            right_panel = QWidget()
            right_panel.setLayout(right_column)
            right_column.setContentsMargins(0, 0, 0, 0)
            right_column.setSpacing(0)

            main_layout.addWidget(self.tree_wrapper)
            main_layout.addWidget(right_panel)
            main_layout.setStretch(0, 1)
            main_layout.setStretch(1, 3)
        except Exception as e:
            emit_gui_exception_log("session_window._setup_main_layout", e)

    # --- Log Update ---
    def _handle_log_update(self, session_id, channel, source, payload, **_):
        """
        Handles incoming log updates and appends them to the log view if the token matches.

        @param str session_id: The session ID.
        @param str channel: The channel name.
        @param str source: The source of the log.
        @param dict payload: The log data payload.
        @private
        """
        try:
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
        except Exception as e:
            emit_gui_exception_log("session_window._handle_log_update", e)


    def _on_log_count_changed(self, count: int):
        """
        Callback triggered when the number of lines in the log view changes.

        @param int count: The new line count.
        @private
        """
        self._last_log_count = count
        self._update_log_status_bar()

    def toggle_config_panel(self):
        """
        Toggles the visibility of the agent configuration group.
        """
        try:
            group = self.detail_panel.config_group
            visible = not group.isVisible()
            group.setVisible(visible)
            # Optionally: self.control_bar.config_btn.setChecked(visible)
        except Exception as e:
            emit_gui_exception_log("session_window.toggle_config_panel", e)

    def toggle_threads_panel(self):
        """
        Toggles the visibility of the agent inspector/threads group.
        """
        try:
            group = self.detail_panel.inspector_group
            visible = not group.isVisible()
            group.setVisible(visible)
            # Optionally: self.control_bar.threads_btn.setChecked(visible)
        except Exception as e:
            emit_gui_exception_log("session_window.toggle_threads_panel", e)

    def _toggle_log_pause(self):
        """
        Toggles the paused state of the log view.
        @private
        """

        try:
            self.log_paused = not self.log_paused
            # Optionally: self.control_bar.pause_btn.setChecked(self.log_paused)
            self._update_log_status_bar()
        except Exception as e:
            emit_gui_exception_log("session_window._toggle_log_pause", e)

    def _launch_restart_agent(self, uid: str = None):
        """
        Launches the restart agent modal for a specific agent.

        @param str|None uid: The universal ID of the agent.
        @private
        """
        try:
            if not isinstance(self._restart_agent_panel, RestartAgentPanel):
                self._restart_agent_panel = RestartAgentPanel(
                    session_id=self.session_id,
                    bus=self.bus,
                    conn=self.conn,
                    deployment=self.deployment,
                    parent=self
                )
            self._restart_agent_panel.launch(uid)
        except Exception as e:
            emit_gui_exception_log("session_window._launch_restart_agent_panel", e)

        # --- Delete Agent ---

    def _launch_delete_agent(self, uid: str = None):
        """
        Launches the delete agent modal for a specific agent.

        @param str|None uid: The universal ID of the agent to delete.
        @private
        """

        try:
            if not isinstance(self._delete_agent_panel, DeleteAgentPanel):
                self._delete_agent_panel = DeleteAgentPanel(
                    session_id=self.session_id,
                    bus=self.bus,
                    conn=self.conn,
                    deployment=self.deployment,
                    parent=self
                )
            self._delete_agent_panel.launch(uid)
        except Exception as e:
            emit_gui_exception_log("session_window._launch_delete_agent_modal", e)


    def _launch_replace_agent_source(self):
        """
        Launches the replace agent source panel.
        @private
        """
        try:

            if not isinstance(self._replace_panel, ReplaceAgentPanel):
                self._replace_panel = ReplaceAgentPanel(
                    session_id=self.session_id,
                    bus=self.bus,
                    conn=self.conn,
                    deployment=self.deployment,
                    parent=self
                )
            self._replace_panel.launch()
        except Exception as e:
            emit_gui_exception_log("session_window._launch_replace_agent_source", e)

    def _launch_multiplexer(self):
        """
        Launches the multiplexer panel for managing outgoing connections.
        @private
        """
        try:
            if not hasattr(self, "_multiplexer_dialog") or not isinstance(self._multiplexer_dialog, MultiplexerPanel):
                self._multiplexer_dialog = MultiplexerPanel(
                    session_id=self.session_id,
                    bus=self.bus,
                    node=None,
                    session_window=self,
                )

            self._multiplexer_dialog.sync_with_current_connector()

            self._multiplexer_dialog.show()
            self._multiplexer_dialog.raise_()
            self._multiplexer_dialog.activateWindow()

        except Exception as e:
            emit_gui_exception_log("session_window._launch_multiplexer", e)

    def _get_connection_launcher(self):
        """
        Fetch the session ConnectionLauncher if available.
        """
        try:
            if self.ctx and isinstance(self.ctx.group, dict):
                return self.ctx.group.get("connection_launcher")
        except Exception as e:
            emit_gui_exception_log("SessionWindow._get_connection_launcher", e)
        return None

    def switch_inbound_connector(self, selected_uid: str):
        """
        Make one payload.reception connector authoritative.

        Behavior:
          1. Update preferred incoming UID
          2. Update inbound dispatcher selector
          3. Stop all other payload.reception connector threads
          4. Launch the selected payload.reception connector
          5. Update badge/status text
        """
        try:
            if not selected_uid:
                print("[SESSION][INBOUND] No selected_uid provided.")
                return False

            selected_agent = None
            incoming_agents = []

            for a in self.deployment.get("agents", []):
                conn = a.get("connection", {}) or {}
                channel = (conn.get("channel") or "").strip().lower()
                if channel == "payload.reception":
                    incoming_agents.append(a)
                    if a.get("universal_id") == selected_uid:
                        selected_agent = a

            if not selected_agent:
                print(f"[SESSION][INBOUND] No payload.reception agent found for uid={selected_uid}")
                return False

            launcher = self._get_connection_launcher()
            if not launcher:
                print("[SESSION][INBOUND] No connection_launcher available.")
                return False

            # 2) Make only the selected ingress live/monitored, then launch it
            try:
                for a in incoming_agents:
                    uid = a.get("universal_id")
                    is_selected = (uid == selected_uid)

                    launcher.update_policy(
                        uid,
                        auto_start=is_selected,
                        monitor=is_selected,
                        ready=True,
                        reason="selected ingress" if is_selected else "dormant ingress",
                    )

                    if not is_selected:
                        launcher.kill_thread(uid)

                t = launcher.launch(selected_uid, fire_catapult=True)

                if not t:
                    print(f"[SESSION][INBOUND] Launch returned no thread for {selected_uid}")
                    return False

                print(f"[SESSION][INBOUND] Launched ingress connector → {selected_uid}")

            except Exception as e:
                emit_gui_exception_log(f"SessionWindow.switch_inbound_connector.launch:{selected_uid}", e)
                return False

            # 2) Update session preference + dispatcher binding
            self.preferred_incoming_uid = selected_uid
            self.inbound_dispatcher.set_inbound_connector(selected_agent)

            # 3) Update UI
            self.incoming_badge.setText(f"Incoming: {selected_uid}  ⚪")
            self.status_label.setText(f"Status: Incoming payload.reception set to {selected_uid}")

            return True

        except Exception as e:
            emit_gui_exception_log("SessionWindow.switch_inbound_connector", e)
            return False

    def _launch_hotswap_agent_modal(self, uid: str = None):
        """
        Launches the hotswap agent modal.

        @param str|None uid: The universal ID of the agent.
        @private
        """
        try:

            if not isinstance(self._hotswap_panel, HotswapAgentPanel):

                self._hotswap_panel = HotswapAgentPanel(
                    session_id=self.session_id,
                    bus=self.bus,
                    conn=self.conn,
                    deployment=self.deployment,
                    parent=self
                )
            tree_data=self.tree.get_rendered_tree()
            self._hotswap_panel.launch(tree_data, uid)

        except Exception as e:
            emit_gui_exception_log("SessionWindow._launch_hotswap_agent_modal", e)

    def _launch_inject_agent_modal(self, uid: str = None):
        """
        Launches the inject agent modal.

        @param str|None uid: The universal ID of the agent.
        @private
        """
        try:

            if not isinstance(self._inject_panel, InjectAgentPanel):

                self._inject_panel = InjectAgentPanel(
                    session_id=self.session_id,
                    bus=self.bus,
                    conn=self.conn,
                    deployment=self.deployment,
                    parent=self
                )

            self._inject_panel.launch(uid)

        except Exception as e:
            emit_gui_exception_log("SessionWindow._launch_inject_agent_modal", e)

    def _launch_matrix_reboot(self):
        """
        Launches the matrix reboot / redeploy dialog.
        @private
        """
        try:

            # Ask cockpit for the full registry
            data = self.vault_singleton.fetch_fresh(target="registry")
            ssh_map = data.get("ssh", {})

            if not ssh_map:
                QtWidgets.QMessageBox.warning(self, "No SSH Targets", "No SSH configurations found in the vault.")
                return

            # Which SSH serial was saved in this deployment?
            default_serial = self.deployment.get("ssh_serial")

            dlg = DeployDialog(
                ssh_map=ssh_map,
                default_serial=default_serial,
                deployment=self.deployment,
                parent=self
            )

            dlg.exec()

        except Exception as e:
            print(f"[CONTROL][ERROR] {e}")

    def show_crypto_alert_panel(self):
        """
        Displays the crypto alert specialty panel.
        """
        if "crypto_alert_panel" not in self._panel_cache:
            panel = CryptoAlertPanel(
                session_id=self.session_id,
                bus=self.bus,
                session_window=self
            )
            self._panel_cache["crypto_alert_panel"] = panel
            self.stacked.addWidget(panel)
        else:
            panel = self._panel_cache["crypto_alert_panel"]

        self.show_specialty_panel(panel)


    def _update_log_status_bar(self):
        """
        Updates the internal status label for the log panel with current state.
        @private
        """
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
    def _send_cmd(self, cmd):
        """
        Placeholder for sending a command. (Unused)

        @param any cmd: The command to send.
        @private
        """
        pass

    def _setup_status_bar(self):
        """
        Initializes and populates the bottom status bar with info badges.
        @private
        """
        try:
            status_bar = QToolBar("Session Status", self)
            status_bar.setMovable(False)

            # Primary status label
            status_bar.addWidget(self.status_label)

            # --- NEW BADGES ---
            self.incoming_badge = QLabel("Incoming: —")
            self.incoming_badge.setStyleSheet("padding-left: 12px; color: #8f8f8f;")
            status_bar.addWidget(self.incoming_badge)

            self.outgoing_badge = QLabel("Outgoing: —")
            self.outgoing_badge.setStyleSheet("padding-left: 12px; color: #8f8f8f;")
            status_bar.addWidget(self.outgoing_badge)

            # session ID shown at far right
            self.session_id_label = QLabel(f"🆔 {self.session_id}")
            self.session_id_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            status_bar.addWidget(self.session_id_label)

            self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, status_bar)

        except Exception as e:
            emit_gui_exception_log("session_window._setup_status_bar", e)

    def _handle_swarm_alert(self, session_id, channel, source, payload, **_):
        """
        Handles swarm feed alerts and passes them up to the parent cockpit via IPC.

        @param str session_id: The session ID.
        @param str channel: The channel name.
        @param str source: The source of the alert.
        @param dict payload: The alert data.
        @private
        """
        try:
            if self.conn:

                self.conn.send({"type": "swarm_feed" , "event": {"payload": payload, "session_id": self.session_id}})

        except Exception as e:
            emit_gui_exception_log("SessionWindow._handle_swarm_alert", e)


    def _handle_external_close(self):
        """
        Closes the session window when a force close signal is received from the parent.
        @private
        """
        print(f"[SESSION] Received external close for {self.session_id}")
        self.close()

    def unhook_bus_handlers(self):
        """
        Detach all ConnectorBus event bindings held by a ctx.
        """

        try:
            connector_bus = ConnectorBus.get(self.ctx.id)

            try:
                for event_name, handler in list(
                    getattr(self.ctx, "_bus_refs", [])
                ):
                    connector_bus.off(event_name, handler)
                    print(f"[BUS] 🔌 Unhooked {event_name} from {self.ctx.id}")
            finally:
                getattr(self.ctx, "_bus_refs", []).clear()
                ConnectorBus.release(self.ctx.id)

            if hasattr(self.ctx, "bus"):
                self.ctx.bus.clear()  # Clears SessionBus listeners
                print(f"[BUS] Cleared SessionBus for {self.ctx.id}")

        except Exception as e:
            print(f"[BUS][ERROR] Failed to unhook bus handlers: {e}")

    def closeEvent(self, event):
        """
        Handles the window close event, performing cleanup of dispatchers, panels, and signaling the parent.

        @param QCloseEvent event: The close event.
        """

        print(f"[SESSION] {self.cockpit_id} closing, destroying session")
        try:

            self.bus.off(f"inbound.verified.swarm_feed.alert", self._handle_swarm_alert)
            self.bus.off("channel.status", self._handle_channel_status)
            self.bus.off(f"inbound.verified.agent_log_view.update", self._handle_log_update)
            self.bus.off("gui.agent.selected", self._handle_agent_selected)
            self.bus.off("gui.log.token.updated", self._set_active_log_token)

            for panel in self._panel_cache.values():
                try:
                    #panel._disconnect_signals()
                    panel.closeEvent(event)

                except Exception as e:
                    print(f"[SESSION][CLEANUP] Failed to delete panel: {e}")

            try:
                launcher = self.ctx.group.get("connection_launcher", None)
                if launcher:
                    launcher.destroy_all()
                    print("[SESSION_WINDOW] ✅ All connections destroyed.")
                else:
                    print("[SESSION_WINDOW] ⚠️ No launcher found in ctx.")
            except Exception as e:
                print(f"[SESSION_WINDOW][ERROR] during shutdown: {e}")
            finally:
                self.unhook_bus_handlers()

            self._panel_cache.clear()

        except Exception as e:
            emit_gui_exception_log("SessionWindow.closeEvent.destroy_session", e)
        finally:
            if self.conn:
                try:
                    self.conn.send({
                        "type": "exit",
                        "session_id": self.cockpit_id
                    })

                except (BrokenPipeError, OSError):
                    print("[SESSION][EXIT] Pipe already closed – skipping exit signal.")

            event.accept()

