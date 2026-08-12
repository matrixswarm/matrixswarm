# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import os
import json
import hashlib
import uuid
from PyQt6 import QtWidgets
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QDialog, QPushButton,QWidget
)
from pathlib import Path
from runpy import run_path
from matrix_gui.core.event_bus import EventBus
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from PyQt6.QtWidgets import QInputDialog, QListWidget, QPushButton, QTextEdit, QLabel, QSplitter
from matrix_gui.modules.vault.ui.dump_vault_popup import DumpVaultPopup
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.swarm_workspace.workspace_manager import WorkspaceManagerDialog
from matrix_gui.swarm_workspace.swarm_workspace import SwarmWorkspaceDialog


class DirectiveManagerDialog(QDialog):
    """
    Commander Edition – Directive Manager
    Left: Workspace Manager (click to open full workspace)
    Right: Deployed Directives list (unchanged)
    """

    def __init__(self):
        super().__init__()

        try:
            self.setWindowTitle("Directive Manager – Commander Edition")
            self.setMinimumSize(1100, 700)

            # =============================================================
            # MAIN LAYOUT
            # =============================================================
            main_layout = QVBoxLayout(self)
            splitter = QSplitter()
            main_layout.addWidget(splitter)

            # =============================================================
            # LEFT PANEL — WORKSPACE MANAGER
            # =============================================================
            self.workspace_manager = WorkspaceManagerDialog()
            splitter.addWidget(self.workspace_manager)

            # Hook event: when user opens or creates a workspace
            self.workspace_manager.workspace_selected.connect(self._on_workspace_opened)

            # =============================================================
            # RIGHT PANEL — DEPLOYED DIRECTIVES
            # =============================================================

            deployed_panel = self._build_deployed_panel()
            splitter.addWidget(deployed_panel)

            # Populate initial list of deployments
            self._populate_deployed()

            splitter.setStretchFactor(0, 2)
            splitter.setStretchFactor(1, 1)
            self.setLayout(main_layout)

        except Exception as e:
            emit_gui_exception_log("DirectiveManagerDialog.__init__", e)

    # ------------------------------------------------------------------
    # RIGHT PANEL BUILDER
    # ------------------------------------------------------------------
    def _build_deployed_panel(self):
        """Builds the legacy Deployed Directives panel (right side)."""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        title = QLabel("Deployed Directives")
        title.setStyleSheet("font-weight:bold; color:#00ff88; font-size:14px;")
        layout.addWidget(title)

        btn_row = QHBoxLayout()

        self.deployed_list_widget = QListWidget()
        layout.addWidget(self.deployed_list_widget)

        self.view_swarmkey_btn = QPushButton("View Swarm Key")
        self.view_swarmkey_btn.clicked.connect(self._show_swarm_key)

        btn_row.addWidget(self.view_swarmkey_btn)

        self.delete_deployed_btn = QPushButton("🗑 Delete Deployed")
        btn_row.addWidget(self.delete_deployed_btn)
        layout.addLayout(btn_row)


        self.dump_vault_btn = QPushButton("Dump Vault")
        self.dump_vault_btn.clicked.connect(self._dump_vault)
        btn_row.addWidget(self.dump_vault_btn)

        self.delete_deployed_btn.clicked.connect(self._on_delete_deployed)

        return panel

    # ------------------------------------------------------------------
    # WORKSPACE OPEN HANDLER
    # ------------------------------------------------------------------
    def _on_workspace_opened(self, uuid):
        try:
            if not uuid:
                return
            vcs = VaultCoreSingleton.get()
            workspaces = vcs.data.setdefault("workspaces", {})
            workspace = workspaces.get(uuid)
            if not workspace:
                QMessageBox.warning(self, "Missing Workspace",
                                    f"Workspace {uuid[:8]} not found in vault.")
                return

            base_dir = Path(__file__).resolve().parents[2]
            agents_root = str(base_dir / "agents_meta")

            dlg = SwarmWorkspaceDialog(agents_root, workspace)
            dlg.exec()

            # refresh deployments after close
            #self._refresh_deployed_list()
            self._populate_deployed()

        except Exception as e:
            emit_gui_exception_log("DirectiveManagerDialog._on_workspace_opened", e)

    def _show_swarm_key(self):

        try:
            # Ensure a deployment is selected
            item = self.deployed_list_widget.currentItem()
            if not item:
                QMessageBox.warning(self, "No Selection", "Select a deployed directive first.")
                return

            dep_id = item.text().split(" :: ")[0].strip()
            vcs = VaultCoreSingleton.get()
            dep_store = vcs.get_store("deployments")

            dep = dep_store.get_dep(dep_id)
            if not dep:
                QMessageBox.warning(self, "Not Found", f"Deployment '{dep_id}' not found in vault.")
                return

            swarm_key = dep.get("swarm_key")
            if not swarm_key:
                QMessageBox.warning(self, "No Swarm Key", "This deployment does not have a swarm_key.")
                return

            dlg = QDialog(self)
            dlg.setWindowTitle("Swarm Key")
            layout = QVBoxLayout(dlg)

            text = QTextEdit()
            text.setReadOnly(True)
            text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)  # don’t wrap long keys
            text.setPlainText(swarm_key)
            text.setMinimumWidth(600)  # widen the box
            text.setMinimumHeight(120)  # add some vertical space
            layout.addWidget(text)

            copy_btn = QPushButton("Copy to Clipboard")
            copy_btn.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(swarm_key))
            layout.addWidget(copy_btn)

            btn_close = QPushButton("Close")
            btn_close.clicked.connect(dlg.accept)
            layout.addWidget(btn_close)

            dlg.resize(800, 200)  # sensible default
            dlg.exec()
        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.launch", e)


    def _dump_vault(self):
        """
        Save the entire self.vault_data to a pretty-printed JSON file for debugging.
        """
        try:
            vcs = VaultCoreSingleton.get()  # get the active authoritative instance
            vault_data = vcs.read()  # deep copy of the FULL vault
            vault_str = json.dumps(vault_data, indent=2)
            dlg = DumpVaultPopup(vault_str, parent=self)
            dlg.exec()

        except Exception as e:
            QMessageBox.critical(self, "Dump Failed", str(e))


    def _on_delete_deployed(self):

        try:
            item = self.deployed_list_widget.currentItem()
            if not item:
                QMessageBox.warning(self, "No Selection", "Select a deployed directive to delete.")
                return

            dep_id = item.text().split(" :: ")[0].strip()

            vcs = VaultCoreSingleton.get()
            dep_store = vcs.get_store("deployments")

            deps = dep_store.get_data()
            if dep_id not in deps:
                QMessageBox.warning(self, "Not Found", f"Deployment '{dep_id}' not found in vault.")
                return

            resp = QMessageBox.question(self, "Delete Deployment",
                                        f"Are you sure you want to delete {dep_id}?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if resp != QMessageBox.StandardButton.Yes:
                return

            success = dep_store.delete_dep(dep_id)

            if not success:
                QMessageBox.warning(self, "Error", f"Failed to delete {dep_id}.")

            self.refresh_lists()

        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.launch", e)

    def _populate_deployed(self):
        """Populates the Deployed Directives list from the live vault."""
        try:
            if not hasattr(self, "deployed_list_widget"):
                print("[DEPLOYMENTS] UI not ready yet.")
                return

            self.deployed_list_widget.clear()

            vcs = VaultCoreSingleton.get()
            dep_store = vcs.get_store("deployments")
            deployments = dep_store.get_data() or {}

            if not deployments:
                self.deployed_list_widget.addItem("(no deployments found)")
                return

            for dep_id, dep_val in deployments.items():
                if not isinstance(dep_val, dict):
                    continue
                label = dep_val.get("label", dep_id)
                self.deployed_list_widget.addItem(f"{dep_id} :: {label}")

        except Exception as e:
            emit_gui_exception_log("DirectiveManagerDialog._populate_deployed", e)

    def refresh_lists(self):

        try:
            #self.saved_list_widget.clear()

            vcs = VaultCoreSingleton.get()
            dir_store = vcs.get_store("directives")

            directives =  dir_store.get_data()


            for key, val in  directives.items():
                if not isinstance(val, dict):
                    continue
                #self.saved_list_widget.addItem(f"{key} :: {val.get('label', key)}")

            self.deployed_list_widget.clear()
            vcs = VaultCoreSingleton.get()
            dep_store = vcs.get_store("deployments")

            deployments = dep_store.get_data()
            for key, val in deployments.items():
                if not isinstance(val, dict):
                    continue
                self.deployed_list_widget.addItem(f"{key} :: {val.get('label', key)}")
        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.refresh_lists", e)



    def _open_swarm_workspace(self):
        try:
            vcs = VaultCoreSingleton.get()
            vault_data = vcs.data  # live vault reference

            # 1. pick agent path
            agents_root = vault_data.get("agent_path", "")
            if not agents_root or not Path(agents_root).exists():
                dlg = QFileDialog(self)
                dlg.setFileMode(QFileDialog.FileMode.Directory)
                dlg.setWindowTitle("Select Agent Root Directory")

                if dlg.exec():
                    agents_root = dlg.selectedFiles()[0]
                    vcs.patch("agent_path", agents_root)
                else:
                    return

            # 2. choose workspace
            ws_mgr = WorkspaceManagerDialog(parent=self)
            if ws_mgr.exec() != QDialog.DialogCode.Accepted:
                return

            ws_uuid = ws_mgr.selected_uuid

            # 3. use LIVE workspace reference, NOT vault_data copy
            workspace_data = vcs.data["workspaces"].get(ws_uuid)
            if workspace_data is None:
                QMessageBox.warning(self, "Workspace Missing", "Workspace not found in vault.")
                return

            # 4. Launch workspace editor ONCE
            from matrix_gui.swarm_workspace.swarm_workspace import SwarmWorkspaceDialog
            dlg = SwarmWorkspaceDialog(agents_root, workspace_data)
            dlg.exec()

            # 5. Save updated workspaces
            vcs.patch("workspaces", vcs.data["workspaces"])
            print("[SWARM WORKSPACE] Saved.")

        except Exception as e:
            emit_gui_exception_log("DirectiveManagerDialog._open_swarm_workspace", e)
            print(f"[WORKSPACE][ERROR] {e}")

    def load_selected(self):

        try:
            item = self.saved_list_widget.currentItem()
            if not item:
                return
            uid = item.text().split(" :: ")[0]

            vcs = VaultCoreSingleton.get()
            dir_store = vcs.get_store("directives")
            dir = dir_store.get_dir(uid)
            if not dir:
                return
            self.editor.setPlainText(json.dumps(dir.get("json"), indent=2))
        except Exception as e:
            emit_gui_exception_log("DirectiveManagerDialog.load_selected", e)

    def load_directive_file(self):
        try:
            vcs = VaultCoreSingleton.get()
            vault_data = vcs.read()

            # Use the last stored path if available
            last_path = vault_data.get("last_boot_directive_path", "")
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Directive",
                last_path,
                "JSON or Python (*.json *.py)",
            )
            if not path:
                return

            # Load the directive content
            if path.endswith(".py"):
                data = run_path(path)["matrix_directive"]
            else:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

            # Remember the folder for the next load
            vault_data["last_directive_load_path"] = os.path.dirname(path)
            vcs.patch("last_directive_load_path", vault_data["last_directive_load_path"])

            # Show directive in the editor
            self.editor.setPlainText(json.dumps(data, indent=2))

        except Exception as e:
            QMessageBox.warning(self, "Load Failed", f"Failed to load directive:\n{e}")
            return

        try:
            self.editor.setPlainText(json.dumps(data, indent=2))
        except Exception as e:
            QMessageBox.warning(self, "Editor Load Error", str(e))

    def save_to_vault(self):
        try:
            directive = json.loads(self.editor.toPlainText())
        except Exception as e:
            QMessageBox.warning(self, "Invalid JSON", str(e))
            return

        hval = hashlib.sha256(json.dumps(directive, sort_keys=True).encode()).hexdigest()

        vcs = VaultCoreSingleton.get()
        dir_store = vcs.get_store("directives")
        directives = dir_store.get_data()

        # --- Duplicate check ---
        for uid, meta in directives.items():
            if meta.get("directive_hash") == hval:
                QMessageBox.information(
                    self,
                    "Duplicate Found",
                    f"Already stored as universe ID: {uid}\nLabel: {meta.get('label', 'unnamed')}",
                )
                return

        # --- Ask for label ---
        label, ok = QInputDialog.getText(
            self, "Directive Label", "Enter a label for this directive:"
        )
        if not ok or not label.strip():
            return

        uid = f"directive_{uuid.uuid4().hex[:6]}"

        # --- Store in live vault ---
        directives[uid] = {
            "label": label.strip(),
            "json": directive,
            "directive_hash": hval,
        }

        # Persist to vault (store handles commit + validation)
        dir_store.commit()

        QMessageBox.information(self, "Saved", f"Directive '{label}' saved to vault.")
        self.refresh_lists()

