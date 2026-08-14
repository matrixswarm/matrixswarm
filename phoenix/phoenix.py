# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
"""
Module: Phoenix Cockpit

Provides the main interface and control framework for managing sessions, vaults, and deployments within the application.
The module includes the `PhoenixCockpit` class, which orchestrates operations such as session management, vault unlocking,
tab navigation, and deployment processes. It also contains utility functions for displaying the application interface.

Classes:
    - PhoenixCockpit: Handles the primary logic and UI for controlling sessions, vaults, and deployments.

Functions:
    - show_with_splash: Displays the application with a splash screen.
    - _launch: Launches the main cockpit application.

Attributes:
    - e, app, f: Global attributes relevant to the overall application state.

---

"""
import sys, time, builtins, inspect, json, pprint

from matrix_gui.core.utils.linux_gui_preflight import require_linux_gui_runtime


require_linux_gui_runtime()

print("Python:", sys.version)
try:
    from PyQt6.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
    print("Qt version:", QT_VERSION_STR)
    print("PyQt version:", PYQT_VERSION_STR)
except Exception as e:
    print("PyQt import error:", e)
import sys, multiprocessing
from PyQt6.QtGui import QWindow
from PyQt6.QtWidgets import QVBoxLayout, QMainWindow,  QWidget, QHBoxLayout, QPushButton, QApplication,QGraphicsDropShadowEffect, QMessageBox, QStackedWidget, QTabBar, QStatusBar, QLabel, QDialog, QTabWidget
from PyQt6.QtCore import QTimer, Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor, QIcon
from matrix_gui.core.session_window import run_session

import matrix_gui.config.boot.boot #don't take this out, looks like it's not doing anything but it setups event listeners
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from matrix_gui.core.event_bus import SessionRegistry
from matrix_gui.core.splash import PhoenixSplash
from matrix_gui.modules.vault.ui.vault_popup import VaultPasswordDialog

#vault dialog
from matrix_gui.modules.vault.vault_selector_dialog import VaultSelectorDialog
from matrix_gui.modules.vault.vault_create_dialog import VaultCreateDialog
from matrix_gui.modules.vault.vault_unlock_dialog import VaultUnlockDialog
from matrix_gui.modules.vault.vault_change_password_dialog import VaultChangePasswordDialog
from matrix_gui.modules.vault.vault_service import VaultService

from matrix_gui.core.event_bus import EventBus
from matrix_gui.core.phoenix_control_panel import PhoenixControlPanel
from matrix_gui.util.resolve_matrixswarm_base import resolve_matrixswarm_base
from matrix_gui.core.panel.home.phoenix_static_panel import PhoenixStaticPanel
from matrix_gui.config.boot.globals import get_sessions
from matrix_gui.core.utils.ui_toast import show_toast
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton

# Define the debug function
#Flip DEBUG_VISUAL to True only when you want it inside your GUI console.
DEBUG_VISUAL = False

def d(*variables, pretty=False, width=100):
    frame = inspect.currentframe().f_back
    var_names = frame.f_locals
    output = []
    for var in variables:
        name = next((key for key, value in var_names.items() if value is var), repr(var))
        if pretty:
            try:
                formatted = json.dumps(var, indent=2, ensure_ascii=False)
            except Exception:
                formatted = pprint.pformat(var, width=width, compact=False)
            out = f"\n{name}:\n{formatted}\n"
        else:
            out = f"{name}: {var!r}"
        output.append(out)
    print("\n".join(output), file=sys.__stdout__)
# make it global
builtins.d = d

class PhoenixCockpit(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("MatrixSwarm :: PHOENIX COCKPIT")
        self.setGeometry(100, 100, 1200, 800)
        self.setMinimumSize(1000, 600)

        self.sessions = None

        #number of active sessions
        self._active_sessions = set()

        base = resolve_matrixswarm_base()
        self.default_vault_dir = base / "matrix_gui" / "vaults"
        self.default_vault_dir.mkdir(parents=True, exist_ok=True)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # === Main Layout: control + tab zone + feed ===
        self.main_layout = QVBoxLayout(self.central_widget)

        # CONTROL PANEL (Top)
        self.control_panel = PhoenixControlPanel()


        self.status_bar = QStatusBar()

        self.status_bar.setFixedHeight(24)

        # Window Icon
        logo_path = "matrix_gui/theme/main_panel_logo.png"
        self.setWindowIcon(QIcon(logo_path))

        # status bar
        self.status_vault = QLabel("Vault: 🔒")
        self.status_deployments = QLabel("Deployments: 0")
        self.status_sessions = QLabel("Sessions: 0")

        self.status_bar = QStatusBar()
        self.status_bar.addPermanentWidget(self.status_vault)
        self.status_bar.addPermanentWidget(self.status_deployments)
        self.status_bar.addPermanentWidget(self.status_sessions)
        self.setStatusBar(self.status_bar)

        # === Legacy Controls (optional override) ===
        self.unlock_button = QPushButton("🔐 UNLOCK")
        self.unlock_button.setFixedSize(160, 60)


        self.unlock_button.clicked.connect(self.unlock_vault)
        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(self.unlock_button)
        button_row.addStretch()

        # top controls
        self.main_layout.setStretchFactor(self.control_panel, 0)

        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.session_commands = {}
        self.forward_listeners = {}

        self.main_layout.setStretchFactor(self.control_panel, 0)  # fixed top
        #self.main_layout.setStretchFactor(self.status_bar, 0)  # fixed bottom

        self.tab_stack = QTabWidget()
        self.tab_stack.setTabsClosable(True)
        self.tab_stack.tabCloseRequested.connect(self._on_tab_close_requested)
        self.main_layout.addWidget(self.tab_stack)

        self.static_panel = PhoenixStaticPanel(
            tab_widget=self.tab_stack,
            tab_index=0
        )
        self.static_panel.setObjectName("HomeTab")
        self.tab_stack.addTab(self.static_panel, " 🜂 Dashboard")
        self.tab_stack.currentChanged.connect(self._on_tab_changed)

        self.tab_stack.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)

        shadow = QGraphicsDropShadowEffect(self.unlock_button)
        shadow.setColor(QColor( 0, 0, 255))
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 0)

        # --- Locked screen ---
        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack)

        # --- Locked screen ---
        self.locked_screen = QWidget()
        lock_layout = QVBoxLayout(self.locked_screen)
        lock_layout.addStretch()
        lock_layout.addWidget(self.unlock_button, alignment=Qt.AlignmentFlag.AlignCenter)
        lock_layout.addStretch()

        # --- Unlocked cockpit ---
        self.unlocked_screen = QWidget()
        cockpit_layout = QVBoxLayout(self.unlocked_screen)
        cockpit_layout.setContentsMargins(0, 0, 0, 0)
        cockpit_layout.setSpacing(0)
        cockpit_layout.addWidget(self.control_panel)
        cockpit_layout.addWidget(self.tab_stack)
        cockpit_layout.setStretchFactor(self.tab_stack, 1)
        cockpit_layout.setStretch(0, 0)  # control panel fixed height
        cockpit_layout.setStretch(1, 0)  # static panel fixed height
        cockpit_layout.setStretch(2, 1)  # tab stack eats remainder


        self.stack.addWidget(self.locked_screen)  # index 0
        self.stack.addWidget(self.unlocked_screen)  # index 1
        self.stack.setCurrentIndex(0)  # start locked



        self.anim = QPropertyAnimation(shadow, b"blurRadius")
        self.anim.setStartValue(20)
        self.anim.setEndValue(50)
        self.anim.setDuration(1000)
        self.anim.setLoopCount(-1)
        self.anim.start()

        self.sessions = None
        self.dispatcher = None

        #status bar
        #self.status_bar = QStatusBar()
        #self.status_bar.setStyleSheet("color: #33ff33; background-color: #111; font-family: Courier;")
        #self.status_bar.setFixedHeight(24)
        #self.main_layout.addWidget(self.status_bar)

        #self.status_bar.addPermanentWidget(QLabel("Matrix Ready"))
        #self.status_bar.addPermanentWidget(QLabel("WS: Connected"))

        self.session_processes = []

        EventBus.on("vault.closed", self._destroy_all_sessions)
        #EventBus.on("vault.update", self._on_vault_update)
        EventBus.on("session.open.requested", self.launch_session)
        EventBus.on("vault.unlocked", self._on_vault_unlocked_ui_flip)
        EventBus.on("vault.reopen.requested", self._on_vault_reopen_requested)

        self._start_pipe_monitor()

        self.show()

    def launch_session(self, session_id: str, deployment: dict, vault_data: dict = None):
        try:
            from multiprocessing import Process, Pipe
            parent_conn, child_conn = Pipe()
            p = Process(target=run_session, args=(session_id, child_conn))
            p.start()

            # --- Immediately send the deployment to the child (no handshake waiting) ---
            parent_conn.send({
                "type": "init",
                "session_id": session_id,
                "deployment": deployment,
                "vault_data": vault_data
            })

            # Wait for child to report its native window id
            win_id = None
            for _ in range(40):
                if parent_conn.poll(0.2):
                    msg = parent_conn.recv()
                    if msg.get("type") == "window_ready" and msg.get("session_id") == session_id:
                        win_id = int(msg.get("win_id"))
                        break

            if not win_id:
                print(f"[MIRV] ❌ Session {session_id} did not report a window id.")
                return

            # Build the embedded container tab
            remote_window = QWindow.fromWinId(win_id)
            remote_window.setFlags(Qt.WindowType.FramelessWindowHint)
            container = QWidget.createWindowContainer(remote_window)
            container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            container.setMinimumSize(800, 600)
            container.setStyleSheet("background-color: #111;")

            tab = QWidget()
            layout = QVBoxLayout(tab)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(container)

            label = f"{deployment.get('label', 'session')} ▸ {session_id[:6]}"
            idx = self.tab_stack.addTab(tab, label)
            self.tab_stack.setCurrentIndex(idx)

            # Use direct reference, not index
            self.session_processes.append({
                "proc": p,
                "conn": parent_conn,
                "session_id": session_id,
                "tab": tab,  # store the widget itself
            })

            self._active_sessions.add(session_id)
            self.status_sessions.setText(f"Sessions: {len(self._active_sessions)}")

            print(f"[MIRV] 🚀 Embedded session {session_id} (pid={p.pid}, winid={win_id})")

        except Exception as e:
            emit_gui_exception_log("PhoenixCockpit.launch_session", e)


    def _start_pipe_monitor(self):
        self.pipe_timer = QTimer(self)
        self.pipe_timer.timeout.connect(self._poll_pipes)
        self.pipe_timer.start(200)

        # periodic cleanup every 10 seconds
        self.reaper_timer = QTimer(self)
        self.reaper_timer.timeout.connect(self._reap_dead_sessions)
        self.reaper_timer.start(10000)

    def _poll_pipes(self):
        try:
            for sess in list(self.session_processes):
                proc = sess.get("proc")
                conn = sess["conn"]

                # --- Check for dead subprocess ---
                if proc and not proc.is_alive():
                    print(f"[WATCHDOG] 🧨 Session process {proc.pid} is dead.")
                    self._cleanup_session(sess, conn)
                    continue

                # --- Handle inbound messages ---
                try:
                    if conn.poll():
                        msg = conn.recv()
                        self._handle_session_msg(msg, conn)
                except (BrokenPipeError, EOFError, OSError):
                    print(f"[MIRV] 🛑 Session pipe closed for pid={proc.pid if proc else 'unknown'}")
                    self._cleanup_session(sess, conn)

        except Exception as e:
            emit_gui_exception_log("PhoenixCockpit._poll_pipes", e)

    def _reap_dead_sessions(self):
        """Periodically nuke orphaned or crashed session processes."""
        try:
            dead = []
            for sess in list(self.session_processes):
                proc = sess.get("proc")
                conn = sess.get("conn")
                sid = sess.get("session_id")

                # mark if process no longer alive or connection closed
                if not proc or not proc.is_alive() or (conn and conn.closed):
                    dead.append(sess)

            for sess in dead:
                try:
                    print(f"[MIRV] ☠ Reaper removing stale session {sess.get('session_id')}")
                    self._cleanup_session(sess, sess.get("conn"))
                except Exception as e:
                    print(f"[MIRV][WARN] Reaper failed for {sess.get('session_id')}: {e}")

            if dead:
                # resync counters
                self.status_sessions.setText(f"Sessions: {len(self._active_sessions)}")

        except Exception as e:
            print(f"[MIRV][ERROR] Reaper loop failed: {e}")

    def _cleanup_session(self, sess, conn):
        try:
            proc = sess.get("proc")
            if proc and proc.is_alive():
                proc.terminate()
                proc.join(timeout=1)
            self.session_processes = [s for s in self.session_processes if s["conn"] != conn]
            self._active_sessions.discard(sess.get("session_id"))
            self.status_sessions.setText(f"Sessions: {len(self._active_sessions)}")
            print(f"[MIRV] 🧹 Cleaned up dead session {sess.get('session_id')}")
        except Exception as e:
            print(f"[MIRV][WARN] Failed to cleanup session: {e}")

    def _on_tab_changed(self, index):
        widget = self.tab_stack.widget(index)
        if isinstance(widget, PhoenixStaticPanel):
            widget._has_unread_alert = False
            widget._update_static_tab_indicator()

    def _handle_session_msg(self, msg, conn):
        """
        Handle messages coming back from session processes.
        Ensures session counter always stays accurate.
        """

        try:
            mtype = msg.get("type")
            sid = msg.get("session_id")

            if mtype == "ready":
                print(f"[MIRV] Session {sid} READY")

            elif mtype == "swarm_feed":
                event = msg.get("event")

                if not event:
                    print("[MIRV][WARN] swarm_feed message missing event dict:", msg)
                    return
                if self.static_panel:
                    self.static_panel.handle_feed_event(event)


            elif mtype == "vault.query":

                dep_id = msg.get("dep_id")

                target = msg.get("target", "deployment")

                if not dep_id:
                    print("[VAULT][WARN] vault.query missing dep_id")

                    return

                try:

                    vcs = VaultCoreSingleton.get()
                    vault_snapshot = vcs.read()  # full top-level vault data snapshot
                    # Default: backward-compatible deployment access
                    if target == "deployment":
                        dep_store = vcs.get_store("deployments")
                        data = dep_store.get_dep(dep_id)
                    # New: full registry map
                    elif target == "registry":
                        # some VaultCores expose .data, others use .read() or a namespace map helper
                        reg_store = vcs.get_store("registry")
                        if hasattr(reg_store, "get_namespace_map"):
                            data = reg_store.get_namespace_map()
                        elif hasattr(reg_store, "data"):
                            data = reg_store.data
                        else:
                            data = vault_snapshot.get("registry", {})
                    # Allow optional full vault read
                    elif target == "vault":
                        data = vault_snapshot

                    # Any other top-level section (workspaces, connection_manager, etc.)
                    elif target in vault_snapshot:
                        data = vault_snapshot.get(target, {})
                    else:
                        print(f"[VAULT][WARN] Unknown target for vault.query: {target}")
                        data = {}

                    # Send back to the session process
                    resp = {
                        "type": "vault.response",
                        "dep_id": dep_id,
                        "target": target,
                        "data": data,
                    }
                    conn.send(resp)
                    print(f"[VAULT] 📤 Sent vault.response target='{target}' for {dep_id}")
                except Exception as e:
                    print(f"[VAULT][ERROR] vault.query failed: {e}")



            elif mtype == "vault.update.requested":

                dep_id = msg.get("dep_id")
                patch = msg.get("patch", {})

                if not dep_id:
                    print(f"[VAULT][WARN] vault.update.requested missing dep_id")
                    return

                vcs = VaultCoreSingleton.get()
                dep_store = vcs.get_store("deployments")
                success = dep_store.update_dep(dep_id, patch)
                if success:
                    print(f"[VAULT] ✅ Deployment '{dep_id}' patched with keys: {list(patch.keys())}")
                else:
                    print(f"[VAULT] ❌ Patch rejected for '{dep_id}' — validation failed.")

            elif mtype == "heartbeat":
                for sess in self.session_processes:
                    if sess["conn"] == conn:
                        sess["last_heartbeat"] = time.time()
                        break
                return

            elif mtype == "register_cmd":
                control = msg["control"]
                action = msg["action"]
                ctx = get_sessions().get(sid)
                try:
                    mod_path = f"matrix_gui.core.factory.cmd.{control}.{action}"
                    mod = __import__(mod_path, fromlist=["*"])
                    class_name = "".join([p.capitalize() for p in action.split("_")]) + "Command"
                    CmdClass = getattr(mod, class_name)

                    existing = next((c for c in self.session_commands.get(sid, [])
                                     if isinstance(c, CmdClass)), None)

                    if not existing:
                        cmd = CmdClass(sid, conn, ctx.bus)
                        cmd.initialize()
                        self.session_commands.setdefault(sid, []).append(cmd)
                        print(f"[MIRV] ✅ Registered {action} for session {sid}")
                except Exception as e:
                    print(f"[MIRV][ERROR] Failed to register cmd={action}: {e}")

            elif mtype == "cmd":
                control = msg["control"]
                action = msg["action"]
                try:
                    mod_path = f"matrix_gui.core.factory.cmd.{control}.{action}"
                    mod = __import__(mod_path, fromlist=["*"])
                    class_name = "".join([p.capitalize() for p in action.split("_")]) + "Command"
                    CmdClass = getattr(mod, class_name)
                    existing = next((c for c in self.session_commands.get(sid, [])
                                     if isinstance(c, CmdClass)), None)
                    if existing:
                        existing.fire_event(**msg)
                        print(f"[MIRV] ✅ Executed {action} via {CmdClass.__name__}")
                except Exception as e:
                    print(f"[MIRV][ERROR] Failed to execute cmd={action}: {e}")

            elif mtype == "ui_toast":

                message = msg.get("message", "Action completed.")
                QTimer.singleShot(0, lambda: show_toast(message))


            elif mtype == "exit":

                sid = msg.get("session_id")
                print(f"[MIRV] 🛑 Session {sid} requested exit")

                # Find the matching session record
                sess = next((s for s in self.session_processes if s["conn"] == conn), None)
                if not sess:
                    print(f"[MIRV][WARN] No matching session found for exit request {sid}")
                    return
                try:
                    proc = sess["proc"]
                    # Close connection cleanly
                    try:
                        conn.close()
                    except Exception:
                        pass
                    # Kill process if still running
                    if proc.is_alive():
                        proc.terminate()
                        proc.join(timeout=2)
                        if proc.is_alive():
                            print(f"[MIRV][WARN] Process {proc.pid} still alive after terminate()")
                        else:
                            print(f"[MIRV] Process {proc.pid} terminated")
                    # Remove UI tab if exists
                    tab = sess.get("tab")
                    tab_index = self.tab_stack.indexOf(tab) if tab is not None else -1
                    if tab_index >= 0:
                        self.tab_stack.removeTab(tab_index)
                        print(f"[MIRV] Closed tab for session {sid}")
                    # Drop from tracking structures
                    self.session_processes = [s for s in self.session_processes if s is not sess]
                    self._active_sessions.discard(sid)
                    # Update status bar
                    self.status_sessions.setText(f"Sessions: {len(self._active_sessions)}")
                    print(f"[MIRV] Session {sid} fully cleaned up")

                except Exception as e:

                    emit_gui_exception_log("PhoenixCockpit._handle_session_msg.exit_cleanup", e)

            else:
                print(f"[MIRV] Unknown msg {msg}")

        except Exception as e:
            emit_gui_exception_log("PhoenixCockpit._handle_session_msg", e)

    def _on_vault_unlocked_ui_flip(self, **kwargs):

        try:

            vault_data = kwargs.get("vault_data")

            # Defensive normalize
            if isinstance(vault_data, bytes):
                try:
                    import json
                    vault_data = json.loads(vault_data.decode("utf-8"))
                except Exception:
                    vault_data = {}

            # If another emitter fired empty kwargs, just ignore it
            if not isinstance(vault_data, dict) or "deployments" not in vault_data:
                print("[VAULT][WARN] Ignoring vault.unlocked with invalid or empty vault_data payload.")
                return

            try:
                #unlock button
                self.stack.setCurrentIndex(1)


                self.fade = QPropertyAnimation(self.unlocked_screen, b"windowOpacity")
                self.fade.setStartValue(0.0)
                self.fade.setEndValue(1.0)
                self.fade.setDuration(400)
                self.fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
                self.fade.start()

                self.control_panel.deployments = getattr(self, "deployments", {})
                self.control_panel.connection_groups = getattr(self, "connection_groups", {})
                self.control_panel.directives = getattr(self, "directives", {})

                #static panel
                self.static_panel.setVisible(True)

                self.unlock_button.hide()
                self.control_panel.setVisible(True)
                self.control_panel.setEnabled(True)
            except Exception as e:
                emit_gui_exception_log("PhoenixControlPanel.launch", e)

            vcs = VaultCoreSingleton.get()
            deployments = vcs.read().get("deployments", {})
            dep_count = len(deployments)
            self.status_vault.setText("Vault: 🔓")
            self.status_deployments.setText(f"Deployments: {dep_count}")
            self.status_sessions.setText("Sessions: 0")  # reset at unlock

            print("[VAULT-CORE] Initialized central vault authority.")

        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.launch", e)

    def closeEvent(self, ev):
        try:

            print("[MIRV] Cockpit closing, nuking all session processes...")

            # Stop pipe polling first
            if hasattr(self, "pipe_timer") and self.pipe_timer.isActive():
                self.pipe_timer.stop()

            for sess in self.session_processes:
                proc = sess["proc"]
                try:
                    if proc.is_alive():
                        # try graceful close first
                        try:
                            sess["conn"].send({"type": "exit", "session_id": "ALL"})
                        except Exception:
                            pass
                        proc.terminate()
                        print(f"[MIRV] Terminated PID {proc.pid}")
                except Exception as e:
                    print(f"[MIRV][ERROR] Could not kill process: {e}")
            super().closeEvent(ev)

        except Exception as e:
            emit_gui_exception_log("PhoenixCockpit.closeEvent", e)

    def _handle_vault_reload(self):
        EventBus.emit("vault.reopen.requested", save=False)

    # in PhoenixCockpit._destroy_all_sessions
    def _destroy_all_sessions(self, **_):
        for sess in list(self.session_processes):
            try:
                if sess["conn"]:
                    sess["conn"].send({"type": "exit"})
            except Exception:
                pass
            try:
                sess["proc"].terminate()
            except Exception:
                pass

        self.session_processes.clear()
        self._active_sessions.clear()

        # wipe global session containers and tabs
        SessionRegistry.clear()

        while self.tab_stack.count() > 1:
            self.tab_stack.removeTab(1)

        self.status_sessions.setText("Sessions: 0")
        print("[VAULT] All sessions and UI tabs destroyed after vault close.")

    def _on_vault_reopen_requested(self, **kwargs):
        """
        Close current vault → hide UI → emit 'vault.closed' → clear singleton → relaunch unlock flow.
        """
        try:
            # Stop dispatcher/sessions
            if getattr(self, "dispatcher", None):
                try:
                    self.dispatcher._stop = True
                except Exception:
                    pass
                self.dispatcher = None
            if getattr(self, "sessions", None):
                try:
                    self.sessions.clear_all()
                except Exception:
                    pass
                self.sessions = None
        except Exception:
            pass

        # Hide UI elements
        try:
            if getattr(self, "control_panel", None):
                self.control_panel.setVisible(False)
                self.control_panel.setEnabled(False)

            if getattr(self, "static_panel", None):
                self.static_panel.setVisible(False)

            # Optional: hide the status bar if you want it blank until unlock
            # self.status_bar.hide()
        except Exception as e:
            print(f"[UI] Failed to hide elements: {e}")


        # Restore locked screen
        self.stack.setCurrentIndex(0)

        self.unlock_button.setVisible(True)
        self.unlock_button.setEnabled(True)
        self.unlock_button.raise_()

        # Status bar refresh
        self.status_vault.setText("Vault: 🔒")
        self.status_deployments.setText("Deployments: 0")
        self.status_sessions.setText("Sessions: 0")

        # Relaunch unlock flow (optional: prompt user immediately)
        self.unlock_vault()

    def unlock_vault(self):
        """
        Unified vault flow:
            1. Ask user: Unlock / Create / Change Pass
            2. Route to the correct dialog
            3. Initialize the vault runtime cleanly via VaultService
            4. UI flip triggered by vault.unlocked event
        """
        try:
            while True:
                selector = VaultSelectorDialog(self)
                if selector.exec() != QDialog.DialogCode.Accepted:
                    return  # user canceled entire flow

                choice = selector.selection

                # ---- CREATE NEW VAULT ----
                if choice == "create":
                    create_dlg = VaultCreateDialog(self)
                    if create_dlg.exec() != QDialog.DialogCode.Accepted:
                        continue  # return to selector

                    new_path = create_dlg.vault_path
                    new_pw = create_dlg.vault_password

                    # Now force user to unlock it immediately
                    unlock_dlg = VaultUnlockDialog(self)
                    unlock_dlg.vault_path = new_path
                    if unlock_dlg.exec() != QDialog.DialogCode.Accepted:
                        continue  # return to selector

                    VaultService.initialize_runtime(
                        vault_data=unlock_dlg.vault_data,
                        password=new_pw,
                        path=new_path
                    )
                    return

                # ---- UNLOCK EXISTING VAULT ----
                elif choice == "unlock":
                    unlock_dlg = VaultUnlockDialog(self)
                    if unlock_dlg.exec() != QDialog.DialogCode.Accepted:
                        continue  # return to selector

                    VaultService.initialize_runtime(
                        vault_data=unlock_dlg.vault_data,
                        password=unlock_dlg.vault_password,
                        path=unlock_dlg.vault_path
                    )
                    return

                # ---- CHANGE VAULT PASSWORD ----
                elif choice == "change":
                    change_dlg = VaultChangePasswordDialog(self)
                    if change_dlg.exec() != QDialog.DialogCode.Accepted:
                        continue  # return to selector

                    QMessageBox.information(
                        self,
                        "Password Updated",
                        "Vault password has been successfully updated.\n"
                        "Please unlock the vault again."
                    )
                    continue  # After password change, return to selector

                else:
                    return

        except Exception as e:
            emit_gui_exception_log("PhoenixCockpit.unlock_vault", e)

    def _on_tab_close_requested(self, index: int):
        try:
            tab = self.tab_stack.widget(index)
            if not tab:
                return

            # Find the session that owns this exact tab widget
            sess = next((s for s in self.session_processes if s.get("tab") == tab), None)
            if not sess:
                self.tab_stack.removeTab(index)
                return

            conn = sess.get("conn")
            proc = sess.get("proc")
            sid = sess.get("session_id")

            # --- Tell session to close ---
            if conn:
                try:
                    conn.send({"type": "force_close"})
                    print(f"[MIRV] 🔻 Sent force_close to {sid}")
                    # give the subprocess a moment to react
                    wait_start = time.time()
                    while proc.is_alive() and time.time() - wait_start < 1.5:
                        QApplication.processEvents()
                        time.sleep(0.05)
                except Exception as e:
                    print(f"[MIRV][WARN] Failed to send force_close to {sid}: {e}")

            # --- Remove the tab safely ---
            self.tab_stack.removeTab(index)

            # --- Kill process if still alive ---
            if proc and proc.is_alive():
                proc.terminate()
                proc.join(timeout=2)

            # --- Cleanup bookkeeping ---
            self.session_processes = [s for s in self.session_processes if s is not sess]
            self._active_sessions.discard(sid)
            self.status_sessions.setText(f"Sessions: {len(self._active_sessions)}")
            print(f"[MIRV] 🧹 Cleaned up session {sid}")

        except Exception as e:
            emit_gui_exception_log("PhoenixCockpit._on_tab_close_requested", e)


def show_with_splash(app, main_cls, delay=4000):
    """
    Displays the application with a splash screen during startup.

    Steps:
        1. Initializes the splash screen with a loading animation or progress information.
        2. Boots the application's main cockpit interface.
        3. Closes the splash screen after successful initialization.
    """
    splash = PhoenixSplash()
    splash.show()

    def launch():
        splash.hide()
        cockpit = main_cls()
        cockpit.show()
        # give Qt compositor a full frame before freeing splash
        QTimer.singleShot(500, splash.deleteLater)

    QTimer.singleShot(delay, launch)


def _launch(app, splash, main_cls):
    """
    Launches the main cockpit application object (`PhoenixCockpit`) and displays it to the user.

    Returns:
        PhoenixCockpit instance: The instance of the cockpit application being launched.
    """
    splash.close()
    cockpit = main_cls()
    cockpit.show()

if __name__ == '__main__':

    multiprocessing.freeze_support()
    app = QApplication(sys.argv)

    # Load Hive stylesheet
    try:
        with open("matrix_gui/theme/icons.qss", "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
        with open("matrix_gui/theme/hive_theme.qss", "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    except Exception as e:
        print(f"[HIVE/STYLE] Failed to load stylesheet: {e}")

    show_with_splash(app, PhoenixCockpit, delay=4000)

    sys.exit(app.exec())
