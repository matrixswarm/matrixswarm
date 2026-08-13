# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import uuid
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QMessageBox, QMenu
from PyQt6 import QtCore

from PyQt6.QtWidgets import QComboBox
from matrix_gui.core.event_bus import EventBus
from matrix_gui.modules.directive.directive_manager_dialog import DirectiveManagerDialog
from matrix_gui.modules.net.connection_manager_dialog import ConnectionManagerDialog
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.registry.registry_manager_v2 import RegistryManagerDialogV2

from matrix_gui.modules.railgun.railgun_check_dialog import RailgunCheckDialog
from matrix_gui.modules.railgun.railgun_install_dialog import RailgunInstallDialog
#from matrix_gui.modules.railgun.railgun_reinstall_dialog import RailgunReinstallDialog

from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from PyQt6.QtWidgets import QFileDialog

class PhoenixControlPanel(QWidget):
    """
    Thin top-bar widget that lets the user unlock a vault, pick a
    deployment profile, and spin up a live Phoenix *SessionWindow*.

    Signals
    -------
    vault_updated(dict)
        Emitted after the connection-manager dialog mutates ``self.vault_data``.
    request_vault_save(dict)
        Ask the cockpit to persist the in-memory vault copy to disk.
    request_vault_load()
        Ask the cockpit to (re)load a vault from disk.
    """
    vault_updated = QtCore.pyqtSignal(dict)
    request_vault_save = QtCore.pyqtSignal(dict)
    request_vault_load = QtCore.pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)

        try:
            self.layout = QHBoxLayout(self)
            self.layout.setContentsMargins(4, 4, 4, 4)
            self.layout.setSpacing(8)

            # === Primary Controls ===
            self.layout.addWidget(QLabel("Deployment:"))
            self.deployment_selector = QComboBox()
            self.layout.addWidget(self.deployment_selector)

            self.connect_btn = QPushButton("🖧 Connect")
            self.connect_btn.setObjectName("connect")
            self.connect_btn.clicked.connect(self.launch_deployment_dialog)
            self.layout.addWidget(self.connect_btn)

            self.conn_btn = QPushButton("🗄 Registry")
            self.conn_btn.setObjectName("connMgr")
            self.conn_btn.clicked.connect(self.launch_registry_manager)
            self.layout.addWidget(self.conn_btn)

            self.directives_btn = QPushButton("🗘 Deploy")
            self.directives_btn.setObjectName("document")
            self.directives_btn.clicked.connect(self.open_directive_manager)
            self.layout.addWidget(self.directives_btn)

            #railgun build
            self.build_railgun_menu()

            self.vault_btn = QPushButton(" Vault")
            self.vault_btn.setObjectName("vault")
            self.vault_btn.clicked.connect(self.reopen_vault)
            self.layout.addWidget(self.vault_btn)

            #keep the registry dialog alive
            self._registry_dialog = None

            # Stretch at end to push controls left
            self.layout.addStretch()

            # Wire events
            EventBus.on("vault.unlocked", self.on_vault_unlocked)
            EventBus.on("vault.update", self.on_vault_update)

        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.__init__", e)


    def build_railgun_menu(self):

        try:

            # === Railgun Button ===
            self.railgun_btn = QPushButton("🗱 Railgun")
            self.railgun_btn.setObjectName("railgun")

            # Give Railgun a dropdown menu
            menu = QMenu(self)

            install_action = menu.addAction("Install MatrixOS…")
            install_action.triggered.connect(self.open_railgun_installer)

            check_action = menu.addAction("Check Remote Host…")
            check_action.triggered.connect(self.open_railgun_check)


            self.railgun_btn.setMenu(menu)
            self.layout.addWidget(self.railgun_btn)

        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.launch", e)

    def open_railgun_installer(self):
        """
        Open the Railgun Install dialog.
        This will allow selecting:
        - Local MatrixOS folder OR GitHub download
        - SSH target (from vault)
        - Install path
        - Optional overwrite
        """
        try:
            dlg = RailgunInstallDialog(parent=self)
            dlg.exec()
        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.open_railgun_installer", e)

    def open_railgun_check(self):
        """
        Remote host inspection via SSH.
        """
        try:

            dlg = RailgunCheckDialog(parent=self)
            dlg.exec()
        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.open_railgun_check", e)

    def refresh_deployments(self):
        """Populate Deployment combobox from PhoenixVaultCore."""
        try:

            vault = VaultCoreSingleton.get().read()
            deployments = vault.get("deployments", {})

            self.deployment_selector.clear()

            for dep_id, meta in deployments.items():
                if not isinstance(meta, dict):
                    continue
                label = meta.get("label", dep_id)
                self.deployment_selector.addItem(label, dep_id)

        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.refresh_deployments", e)

    def on_vault_update(self, **kwargs):
        """Handle a ``vault.update`` bus event.

        Parameters
        ----------
        **kwargs
            ``data`` – the fresh vault dict shoved in by the emitter.
        """
        try:
            self.refresh_deployments()
        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.on_vault_update", e)

    from matrix_gui.registry.registry_manager_v2 import RegistryManagerDialogV2

    def launch_registry_manager(self):
        try:
            # Create once
            if self._registry_dialog is None:
                self._registry_dialog = RegistryManagerDialogV2(parent=self)

                # Ensure reference is cleared if user closes it
                self._registry_dialog.finished.connect(self._on_registry_closed)

            # Re-show instead of re-create
            self._registry_dialog.show()
            self._registry_dialog.raise_()
            self._registry_dialog.activateWindow()

        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.launch_registry_manager", e)

    def _on_registry_closed(self, _result=None):
        self._registry_dialog = None

    def launch_deployment_dialog(self):
            """Open a live session for the currently selected deployment.

            Validates that a vault is unlocked and the selected deployment exists,
            then emits the **session.open.requested** bus event with a brand-new
            UUID-4 ``session_id`` and the deployment metadata payload.
            """

            try:
                dep_id = self.deployment_selector.currentData()
                if not dep_id:
                    QMessageBox.warning(self, "No Deployment", "Please select a deployment first.")
                    return

                vault = VaultCoreSingleton.get().read()

                if "deployments" not in vault:
                    QMessageBox.warning(self, "No Vault", "Vault data not loaded or invalid.")
                    return

                deployment = vault["deployments"].get(dep_id)
                if not deployment:
                    QMessageBox.warning(self, "Invalid Deployment", f"Deployment {dep_id} not found in vault.")
                    return

                # Tag deployment with its vault id
                deployment["id"] = dep_id

                # Generate a unique session ID
                session_id = str(uuid.uuid4())

                # Emit session.open.requested with proper signature
                EventBus.emit(
                    "session.open.requested",
                    session_id=session_id,
                    deployment=deployment
                )
            except Exception as e:
                emit_gui_exception_log("PhoenixControlPanel.launch_deployment_dialog", e)

    def reopen_vault(self):
        """Close the active vault and trigger the cockpit’s re-unlock workflow."""
        reply = QMessageBox.question(
            self, "Close current vault?",
            "Are you sure you want to close this vault?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        EventBus.emit("vault.closed")
        EventBus.emit("vault.reopen.requested")

    # =========================================================
    # Vault lifecycle
    # =========================================================
    def on_vault_unlocked(self, **kwargs):
        """Receive the ``vault.unlocked`` signal and cache path / password."""
        self.vault_unlocked = True

        #self.vault_data or {}
        self.refresh_deployments()
        # now that we have vault_data, start sessions + dispatcher
        #self.sessions = SessionManager(EventBus)
        #self.dispatcher = OutboundDispatcher(EventBus, self.sessions, vault=self.vault_data)
        #self.dispatcher.start()

    def open_directive_manager(self):
        dlg = DirectiveManagerDialog()
        dlg.exec()

