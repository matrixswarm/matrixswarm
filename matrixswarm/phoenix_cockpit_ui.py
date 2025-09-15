
# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import os
import sys
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QMainWindow, QVBoxLayout, QApplication,
    QGraphicsDropShadowEffect, QMessageBox
)
#initialize bus
import matrix_gui.config.boot.boot
from PyQt5.QtCore import Qt, QPropertyAnimation
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QStatusBar

from matrix_gui.modules.vault.crypto.vault_handler import load_vault_singlefile
from matrix_gui.modules.vault.services.vault_singleton import VaultSingleton
from matrix_gui.modules.vault.services.vault_obj import VaultObj
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

from matrix_gui.modules.vault.ui.vault_popup import VaultPasswordDialog
from matrix_gui.modules.vault.ui.vault_init_dialog import VaultInitDialog
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QPushButton
from matrix_gui.core.event_bus import EventBus
from matrix_gui.core.phoenix_control_panel import PhoenixControlPanel
from matrix_gui.util.resolve_matrixswarm_base import resolve_matrixswarm_base
from matrix_gui.core.panel.home.phoenix_static_panel import PhoenixStaticPanel
from matrix_gui.config.boot.globals import get_sessions

class PhoenixCockpit(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("MatrixSwarm :: PHOENIX COCKPIT")
        self.setGeometry(100, 100, 1200, 800)
        self.setMinimumSize(1000, 600)
        self.vault_loaded = False
        self.vault_path = None
        self.vault_password = None

        self.sessions = None

        base = resolve_matrixswarm_base()
        self.default_vault_dir = base / "matrix_gui" / "vaults"
        self.default_vault_dir.mkdir(parents=True, exist_ok=True)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # === Main Layout: control + tab zone + feed ===
        self.main_layout = QVBoxLayout(self.central_widget)

        # CONTROL PANEL (Top)
        self.control_panel = PhoenixControlPanel()
        self.main_layout.addWidget(self.control_panel)
        self.control_panel.setVisible(False)  # hide until vault unlock
        self.control_panel.setEnabled(False)
        self.control_panel.request_vault_save.connect(self._handle_vault_save)
        self.control_panel.request_vault_load.connect(self._handle_vault_reload)

        #static panel
        self.static_panel = PhoenixStaticPanel()
        self.main_layout.addWidget(self.static_panel)
        self.static_panel.setVisible(False)

        # === Legacy Controls (optional override) ===
        self.unlock_button = QPushButton("🔐 UNLOCK")
        self.unlock_button.setFixedSize(160, 60)
        self.unlock_button.setStyleSheet("""
                QPushButton {
                    background-color: #222;
                    color: white;
                    font-size: 18px;
                    font-weight: bold;
                    border: 2px solid #888;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    border: 2px solid #fff;
                }
            """)
        self.unlock_button.clicked.connect(self.unlock_vault)
        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(self.unlock_button)
        button_row.addStretch()

        # Center the unlock button vertically
        self.main_layout.addStretch(1)
        self.main_layout.addLayout(button_row)
        self.main_layout.addStretch(1)

        self.session_commands = {}
        self.forward_listeners = {}

        self.main_layout.setStretchFactor(self.control_panel, 0)  # fixed top
        #self.main_layout.setStretchFactor(self.status_bar, 0)  # fixed bottom

        # Optional: decorate with glow
        shadow = QGraphicsDropShadowEffect(self.unlock_button)
        shadow.setColor(QColor( 0, 0, 255))
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 0)
        self.unlock_button.setGraphicsEffect(shadow)

        self.anim = QPropertyAnimation(shadow, b"blurRadius")
        self.anim.setStartValue(20)
        self.anim.setEndValue(50)
        self.anim.setDuration(1000)
        self.anim.setLoopCount(-1)
        self.anim.start()

        self.vault_data = None
        self.vault_password = None
        self.vault_path = None
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

        EventBus.on("session.open.requested", self.launch_session)
        EventBus.on("vault.unlocked", self._on_vault_unlocked_ui_flip)
        EventBus.on("vault.reopen.requested", self._on_vault_reopen_requested)

        self._start_pipe_monitor()

        self.show()

    def launch_session(self, session_id: str, deployment: dict, vault_data: dict = None):
        from multiprocessing import Process, Pipe
        from matrix_gui.core.session_window import run_session

        parent_conn, child_conn = Pipe()
        p = Process(target=run_session, args=(session_id, child_conn))
        p.start()

        parent_conn.send({
            "type": "init",
            "session_id": session_id,
            "deployment": deployment,
            "vault_data": vault_data
        })

        self.session_processes.append({"proc": p, "conn": parent_conn})
        print(f"[MIRV] Launched session {session_id}, pid={p.pid}")

    def _start_pipe_monitor(self):
        self.pipe_timer = QTimer(self)
        self.pipe_timer.timeout.connect(self._poll_pipes)
        self.pipe_timer.start(200)

    def _poll_pipes(self):
        for sess in list(self.session_processes):
            conn = sess["conn"]
            if conn.poll():
                msg = conn.recv()
                self._handle_session_msg(msg, conn)

    def _handle_session_msg(self, msg, conn):


        mtype = msg.get("type")
        sid = msg.get("session_id")

        if mtype == "ready":
            print(f"[MIRV] Session {sid} READY")

        elif mtype == "register_cmd":
            control = msg["control"]
            action = msg["action"]
            sid = msg["session_id"]
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
                    cmd.initialize()  # sets listeners
                    self.session_commands.setdefault(sid, []).append(cmd)
                    print(f"[MIRV] ✅ Registered {action} for session {sid}")
                else:
                    print(f"[MIRV] ℹ️ Command {action} already registered for {sid}")
            except Exception as e:
                print(f"[MIRV][ERROR] Failed to register cmd={action}: {e}")

        elif mtype == "cmd":

            control = msg["control"]
            action = msg["action"]
            sid = msg["session_id"]
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
                else:
                    print(f"[MIRV][ERROR] Command {action} not registered for session {sid}")

            except Exception as e:
                print(f"[MIRV][ERROR] Failed to execute cmd={action}: {e}")

        elif mtype == "exit":

            print(f"[MIRV] Session {sid} EXITED")
            # Tear down commands
            for cmd in self.session_commands.get(sid, []):
                cmd.off_event()
            self.session_commands.pop(sid, None)

            for (event, handler) in self.forward_listeners.get(sid, []):
                try:
                    EventBus.off(event, handler)
                    print(f"[MIRV] 🧹 Unsubscribed {event} for {sid}")
                except Exception as e:
                    print(f"[MIRV] ⚠️ Failed to remove listener {event} for {sid}: {e}")
            self.forward_listeners.pop(sid, None)

            # Remove session process record
            self.session_processes = [s for s in self.session_processes if s["conn"] != conn]

        else:
            print(f"[MIRV] Unknown msg {msg}")

    def _on_vault_unlocked_ui_flip(self, **kwargs):

        try:
            # stash vault for later
            self.vault_data = kwargs.get("vault_data")
            self.vault_password = kwargs.get("password")
            self.vault_path = kwargs.get("vault_path")

            # hand vault to the panel (it also listens to vault.unlocked and will start sessions/dispatcher itself)
            self.control_panel.vault_data = self.vault_data
            self.control_panel.vault_path = self.vault_path
            self.control_panel.password = self.vault_password
            self.control_panel.deployments = getattr(self, "deployments", {})
            self.control_panel.connection_groups = getattr(self, "connection_groups", {})
            self.control_panel.directives = getattr(self, "directives", {})

            #static panel
            self.static_panel.vault_data = self.vault_data
            self.static_panel.vault_path = self.vault_path
            self.static_panel._refresh_deployment_summary()
            self.static_panel.setVisible(True)


            self.unlock_button.hide()
            self.control_panel.setVisible(True)
            self.control_panel.setEnabled(True)

        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.launch", e)

    def closeEvent(self, ev):
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

    def _handle_vault_save(self, vault_data):
        try:
            EventBus.emit("vault.update", data=vault_data,
                          password=self.vault_password,
                          vault_path=self.vault_path)
            QMessageBox.information(self, "Vault Saved", "Vault saved via bus.")
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Vault save failed:\n{e}")

    def _handle_vault_reload(self):
        EventBus.emit("vault.reopen.requested", save=False)

    def _on_vault_reopen_requested(self, **kwargs):
        """
        Close current vault → hide UI → emit 'vault.closed' → clear singleton → relaunch unlock flow.
        """
        # 1) Best-effort: stop background workers/sessions
        try:
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

        # 2) Hide UI
        try:
            if getattr(self, "control_panel", None):
                self.control_panel.setVisible(False)
        except Exception:
            pass

        # 3) Lifecycle event + clear singleton
        old_path = getattr(self, "vault_path", None)
        try:
            EventBus.emit("vault.closed", vault_path=old_path)
        except Exception:
            pass
        try:
            VaultSingleton.clear()
        except Exception:
            pass

        # 4) Reset cockpit state
        self.vault_loaded = False
        self.vault_data = None
        self.vault_password = None
        self.vault_path = None

        # 5) Flip back to "locked" and immediately start open/create flow
        self.unlock_button.setVisible(True)
        self.unlock_button.setEnabled(True)
        self.unlock_button.raise_()
        self.unlock_vault()

    def unlock_vault(self):
        """
        Lean vault open/create coordinator.
        - If no vaults exist: run create dialog, then initialize and emit 'vault.unlocked'.
        - Else: run VaultPasswordDialog; it should decrypt, set the singleton, and emit 'vault.unlocked'.
        Cockpit does not re-load or re-emit; it just coordinates UI.
        """
        # First-run: no vault directory contents → create one
        if not os.listdir(self.default_vault_dir):
            init_dialog = VaultInitDialog(self)
            if init_dialog.exec_() != init_dialog.Accepted:
                return  # user cancelled

            self.vault_path = init_dialog.vault_path
            self.vault_password = init_dialog.vault_password

            # Initialize once, set singleton, emit unlocked (keep payload for compatibility)
            try:
                data = load_vault_singlefile(self.vault_password, self.vault_path)
                try:
                    # If you have a concrete VaultObj, set it; else you can
                    # adapt this to your VaultSingleton API.
                    vobj = VaultObj(
                        path=self.vault_path,
                        vault=data,
                        password=self.vault_password,
                        encryptor=None,
                        decryptor=None,
                    )
                    VaultSingleton.set(vobj)
                except Exception:
                    # Fallback: at least clear/set a minimal state if your singleton API differs
                    pass

                EventBus.emit(
                    "vault.unlocked",
                    vault_data=data,
                    password=self.vault_password,
                    vault_path=self.vault_path
                )
            except Exception as e:
                QMessageBox.critical(self, "Vault Error", f"Failed to initialize vault:\n{str(e)}")
            return

        # Normal path: unlock dialog handles decrypt + singleton + event
        dialog = VaultPasswordDialog(self)
        if dialog.exec_() != dialog.Accepted:
            return
        # Do NOT reload or re-emit here; the dialog already emitted 'vault.unlocked'.
        return


if __name__ == '__main__':
    app = QApplication(sys.argv)
    cockpit = PhoenixCockpit()
    sys.exit(app.exec_())