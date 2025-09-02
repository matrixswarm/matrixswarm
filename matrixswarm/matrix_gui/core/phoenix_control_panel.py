from typing import Optional

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QMessageBox, QSizePolicy
from PyQt5 import QtCore
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QComboBox
from matrix_gui.core.event_bus import EventBus
from matrix_gui.modules.directive.directive_manager_dialog import DirectiveManagerDialog
from matrix_gui.modules.net.connection_manager_dialog import ConnectionManagerDialog
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log

class PhoenixControlPanel(QWidget):
    """
    Control Panel:
      - unlock vault → start SessionManager + OutboundDispatcher
      - choose connection profile → build ConnectionGroup → connect
      - minimal UI; tab lifecycle handled elsewhere (TabStack)
    """
    vault_updated = QtCore.pyqtSignal(dict)
    request_vault_save = QtCore.pyqtSignal(dict)
    request_vault_load = QtCore.pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)

        self.vault_unlocked: bool = False
        self.vault_data = None
        self.vault_path = None
        self.password = None

        # ---- UI ----
        self.layout = QHBoxLayout(self)

        self.vault_status = QLabel("🔒 Vault: locked")

        # Deployment selector
        self.layout.addWidget(QLabel("Deployment:"))
        self.deployment_selector = QComboBox()
        self.layout.addWidget(self.deployment_selector)

        # Buttons with icons + colors
        self.connect_btn = QPushButton(" Connect")
        self.connect_btn.setObjectName("connect")
        self.connect_btn.setIcon(QIcon(":/icons/connect.png"))  # or fromTheme("network-connect")
        self.connect_btn.setIconSize(QtCore.QSize(20, 20))
        self.connect_btn.clicked.connect(self.launch_deployment_dialog)
        self.layout.addWidget(self.connect_btn)

        self.btn_connection_manager = QPushButton(" Connections")
        self.btn_connection_manager.setObjectName("connMgr")
        self.btn_connection_manager.setIcon(QIcon(":/icons/network.png"))
        self.btn_connection_manager.setIconSize(QtCore.QSize(20, 20))
        self.btn_connection_manager.clicked.connect(self.launch_connection_manager)
        self.layout.addWidget(self.btn_connection_manager)

        self.manage_directive_btn = QPushButton(" Directives")
        self.manage_directive_btn.setObjectName("directives")
        self.manage_directive_btn.setIcon(QIcon(":/icons/directive.png"))
        self.manage_directive_btn.setIconSize(QtCore.QSize(20, 20))
        self.manage_directive_btn.clicked.connect(self.open_directive_manager)
        self.layout.addWidget(self.manage_directive_btn)

        self.change_vault_btn = QPushButton(" Vault")
        self.change_vault_btn.setObjectName("changeVault")
        self.change_vault_btn.setIcon(QIcon(":/icons/key.png"))
        self.change_vault_btn.setIconSize(QtCore.QSize(20, 20))
        self.change_vault_btn.clicked.connect(self.reopen_vault)
        self.layout.addWidget(self.change_vault_btn)

        self.layout.addWidget(self.vault_status)
        self.layout.addStretch()

        # ---- bus ----
        EventBus.on("vault.unlocked", self.on_vault_unlocked)

        # --- Style ---
        self.setStyleSheet("""
            QWidget {
                background-color: #f5f6fa;
                color: #222;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
            }
            QComboBox {
                background: #fff;
                border: 1px solid #bbb;
                border-radius: 5px;
                padding: 2px 8px;
                min-width: 70px;
            }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #fafdff, stop:1 #e4e8ee);
                color: #222;
                border: 1.3px solid #d4d7dd;
                border-radius: 7px;
                padding: 5px 16px 5px 16px;
                margin: 0 2px 0 2px;
                font-weight: 500;
                transition: background 0.2s;
            }
            QPushButton:pressed {
                background: #e3e7ee;
            }
            QPushButton:focus {
                border: 1.7px solid #0078d7;
                background: #f0f6ff;
            }
            QPushButton#connect {
                border: 1.7px solid #0078d7;
                color: #0078d7;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #eaf4ff, stop:1 #e3ecfa);
                font-weight: 600;
            }
            QPushButton#connect:hover {
                background: #dbefff;
            }
            QPushButton#changeVault {
                border: 1.4px solid #b53c33;
                color: #b53c33;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #fff3f1, stop:1 #fbe6e4);
            }
            QPushButton#changeVault:hover {
                background: #f5cfc7;
            }
            QLabel {
                font-weight: 500;
            }
            QLabel[vault_status="unlocked"] {
                color: #19b551;
                font-weight: 700;
            }
            QLabel[vault_status="locked"] {
                color: #a94442;
                font-weight: 700;
            }
        """)

        # defer sessions/dispatcher until vault is unlocked (needs keys)
        #self.sessions: Optional[SessionManager] = None
        #self.dispatcher: Optional[OutboundDispatcher] = None

    def refresh_deployments(self):

        try:
            self.deployment_selector.clear()
            deployments = (self.vault_data or {}).get("deployments", {})
            for dep_id, meta in deployments.items():
                if not isinstance(meta, dict):
                    continue  # skip bad entry
                label = meta.get("label", dep_id)
                self.deployment_selector.addItem(label, dep_id)
        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.launch", e)


    def launch_deployment_dialog(self):
        dep_id = self.deployment_selector.currentData()
        if not dep_id:
            QMessageBox.warning(self, "No Deployment", "Please select a deployment first.")
            return

        EventBus.emit("deployment.connect.requested", dep_id=dep_id, vault_data=self.vault_data)
    def launch_connection_manager(self):
        dlg = ConnectionManagerDialog(self.vault_data, self)
        dlg.exec_()
        #self.refresh_deployments()
        self.vault_updated.emit(self.vault_data)


    def save_vault(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Save Vault", filter="Vault JSON (*.json)")
        if path:
            import json
            with open(path, "w") as f:
                json.dump(self.vault_data, f, indent=2)
                QMessageBox.information(self, "Saved", f"Vault saved to {path}")

    def reopen_vault(self):
        reply = QMessageBox.question(
            self,
            "Close current vault?",
            "Are you sure you want to close this vault?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return  # No → do nothing

        # Yes → let the cockpit perform the lifecycle
        EventBus.emit("vault.reopen.requested")

    # =========================================================
    # Vault lifecycle
    # =========================================================
    def on_vault_unlocked(self, **kwargs):
        self.vault_unlocked = True
        self.vault_data = kwargs.get("vault_data")
        self.password = kwargs.get("password")
        self.vault_path = kwargs.get("vault_path")

        self.vault_status.setText(f"🔓 Vault: unlocked") # {self.vault_path or 'unlocked'}")

        #self.vault_data or {}
        self.refresh_deployments()
        # now that we have vault_data, start sessions + dispatcher
        #self.sessions = SessionManager(EventBus)
        #self.dispatcher = OutboundDispatcher(EventBus, self.sessions, vault=self.vault_data)
        #self.dispatcher.start()

    def open_directive_manager(self):
        dlg = DirectiveManagerDialog(
            vault_data=self.vault_data,
            password=self.password,
            vault_path=self.vault_path,
            parent=self
        )
        dlg.exec_()

    def emit_save(self):
        self.request_vault_save.emit(self.vault_data)

    def emit_reload(self):
        self.request_vault_load.emit()

    # =========================================================
    # Misc bus sinks
    # =========================================================
    def on_ops_feed(self, msg: str):
        try:
            print("[OPS]", msg)
        except Exception:
            pass
