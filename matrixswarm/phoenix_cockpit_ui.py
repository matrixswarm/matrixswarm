import os
import sys
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QApplication,
    QGraphicsDropShadowEffect, QHBoxLayout, QTextEdit, QLineEdit, QMessageBox, QSizePolicy
)
#initialize bus
import matrix_gui.config.boot.boot
from PyQt5.QtCore import Qt, QPropertyAnimation, QTimer
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
from matrix_gui.core.phoenix_tab_stack import PhoenixTabStack
from matrix_gui.util.resolve_matrixswarm_base import resolve_matrixswarm_base
from matrix_gui.core.panel.home.phoenix_static_panel import PhoenixStaticPanel

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

        # TAB + OPERATIONS ZONE (Middle)

        self.tab_stack = PhoenixTabStack()
        self.main_layout.addWidget(self.tab_stack)
        self.tab_stack.setVisible(False)  # hide until vault unlock

        #static panel
        self.static_panel = PhoenixStaticPanel()
        self.home_idx = self.tab_stack.tab_widget.insertTab(0, self.static_panel, "🏠 Home")
        self.tab_stack._tab_sessions[self.home_idx] = "HOME"
        self.tab_stack._tab_widgets[self.home_idx] = self.static_panel
        self.tab_stack.tab_widget.setTabEnabled(self.home_idx, False)


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

        self.main_layout.setStretchFactor(self.control_panel, 0)  # fixed top
        self.main_layout.setStretchFactor(self.tab_stack, 1)  # greedy middle
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

        EventBus.on("vault.unlocked", self._on_vault_unlocked_ui_flip)
        EventBus.on("vault.reopen.requested", self._on_vault_reopen_requested)


        self.show()

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
            self.tab_stack.tab_widget.setTabEnabled(self.home_idx, True)
            self.tab_stack.tab_widget.setCurrentIndex(self.home_idx)


            self.unlock_button.hide()
            self.control_panel.setVisible(True)
            self.control_panel.setEnabled(True)
            self.tab_stack.setVisible(True)
        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.launch", e)


    def closeEvent(self, ev):
        try:
            if getattr(self, "dispatcher", None):
                self.dispatcher._stop = True
        finally:
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
            if getattr(self, "tab_stack", None):
                self.tab_stack.setVisible(False)
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