# Authored by Daniel F MacDonald and ChatGPT-5 aka The Generals
import os
import io
import json
import hashlib
import uuid
import base64
import paramiko
import ntpath
import posixpath

from copy import deepcopy
from PyQt6 import QtWidgets, QtCore

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QDialog
)
from pathlib import Path
from runpy import run_path
from matrix_gui.modules.vault.crypto.deploy_tools import generate_swarm_encrypted_directive
from matrix_gui.modules.directive.encryption_staging_dialog import EncryptionStagingDialog
from matrix_gui.modules.directive.ui.deployment_dialog import DeploymentDialog
from matrix_gui.modules.directive.deploy_options_dialog import DeployOptionsDialog
from matrix_gui.core.event_bus import EventBus
from matrix_gui.modules.directive.connection_assignment_dialog import ConnectionAssignmentDialog
from matrix_gui.modules.directive.deployment.helper.mint_directive_for_deployment import mint_directive_for_deployment
from matrix_gui.modules.directive.deployment.helper.mint_deployment_metadata import mint_deployment_metadata
from matrix_gui.core.dialog.agent_root_check_dialog import AgentRootCheckDialog
from matrix_gui.core.class_lib.paths.agent_root_selector import AgentRootSelector
from matrix_gui.core.emit_gui_exception_log import emit_gui_exception_log
from PyQt6.QtWidgets import QInputDialog, QListWidget, QPushButton, QTextEdit, QLabel
from matrix_gui.modules.vault.crypto.deploy_tools import write_encrypted_bundle_to_file
from matrix_gui.modules.directive.deployment.wrapper import agent_aggregator_wrapper, agent_connection_wrapper, agent_cert_wrapper, agent_directive_wrapper , agent_signing_cert_wrapper, agent_symmetric_encryption_wrapper
from matrix_gui.modules.vault.ui.dump_vault_popup import DumpVaultPopup
from matrix_gui.modules.vault.services.vault_core_singleton import VaultCoreSingleton
from matrix_gui.swarm_workspace.workspace_manager import WorkspaceManagerDialog

class DirectiveManagerDialog(QDialog):
    vault_updated = QtCore.pyqtSignal(dict)
    def __init__(self, parent=None):
        super().__init__(parent)

        try:
            self.setWindowTitle("Directive Manager")
            self.setMinimumSize(900, 620)

            #v = self.vault_data
            #for key, val in (self.vault_data.get("deployments") or {}).items():
            #    if not isinstance(val, dict):
            #        continue  # skip corrupted deployment entries
            #    label = val.get("label", key)

            #for key, val in (self.vault_data.get("directives") or {}).items():
            #    if not isinstance(val, dict):
            #        continue
            #    label = val.get("label", key)

            main_layout = QVBoxLayout(self)

            lists_row = QHBoxLayout()

            # -- Saved Directives Panel --
            saved_layout = QVBoxLayout()
            saved_layout.addWidget(QLabel("Saved Directives"))
            self.saved_list_widget = QListWidget()
            saved_layout.addWidget(self.saved_list_widget)
            # --- Button row for Saved Directives ---
            saved_btn_row = QHBoxLayout()
            self.load_btn = QPushButton("Load Directive")
            self.save_btn = QPushButton("Save to Vault")
            self.deploy_btn = QPushButton("Deploy")
            self.delete_saved_btn = QPushButton("Delete Saved")

            saved_btn_row.addWidget(self.load_btn)
            saved_btn_row.addWidget(self.save_btn)
            saved_btn_row.addWidget(self.deploy_btn)
            saved_btn_row.addWidget(self.delete_saved_btn)
            saved_layout.addLayout(saved_btn_row)

            # -- Deployed Directives Panel --
            deployed_layout = QVBoxLayout()
            deployed_layout.addWidget(QLabel("Deployed Directives"))
            self.deployed_list_widget = QListWidget()
            deployed_layout.addWidget(self.deployed_list_widget)
            # --- Button row for Deployed Directives ---
            deployed_btn_row = QHBoxLayout()
            self.delete_deployed_btn = QPushButton("Delete Deployed")
            deployed_btn_row.addWidget(self.delete_deployed_btn)

            deployed_layout.addLayout(deployed_btn_row)

            lists_row.addLayout(saved_layout)
            lists_row.addLayout(deployed_layout)
            main_layout.addLayout(lists_row)

            self.editor = QTextEdit()
            self.editor.setPlaceholderText("Edit directive JSON here...")
            main_layout.addWidget(self.editor)
            self.setLayout(main_layout)

            self.view_swarmkey_btn = QPushButton("View Swarm Key")
            self.view_swarmkey_btn.clicked.connect(self.show_swarm_key)

            deployed_btn_row.addWidget(self.view_swarmkey_btn)

            # -- Connect Buttons --
            self.load_btn.clicked.connect(self.load_directive_file)
            self.save_btn.clicked.connect(self.save_to_vault)
            self.deploy_btn.clicked.connect(self.deploy_directive)
            self.delete_saved_btn.clicked.connect(self.delete_saved_directive)
            self.delete_deployed_btn.clicked.connect(self.delete_deployed)

            self.saved_list_widget.itemClicked.connect(self.load_selected)

            #dump vault button and handler
            self.dump_vault_btn = QPushButton("Dump Vault")
            self.dump_vault_btn.clicked.connect(self.dump_vault)
            saved_btn_row.addWidget(self.dump_vault_btn)

            #use graph to deply
            self.graph_btn = QPushButton("View / Edit Swarm Workspace")
            self.graph_btn.clicked.connect(self._open_swarm_workspace)
            saved_btn_row.addWidget(self.graph_btn)

            self.refresh_lists()
        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.launch", e)

    def show_swarm_key(self):

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


    def dump_vault(self):
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

    def refresh_list(self):

        try:
            self.saved_list_widget.clear()

            vcs = VaultCoreSingleton.get()
            dir_store = vcs.get_store("directives")
            for key, val in dir_store.get_data().items():
                label = val.get("label", key)
                self.saved_list_widget.addItem(f"{key} :: {label}")
        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.launch", e)

    def delete_deployed(self):

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

            if success:
                QMessageBox.information(self, "Deleted", f"Deployment {dep_id} deleted.")
            else:
                QMessageBox.warning(self, "Error", f"Failed to delete {dep_id}.")

            self.refresh_lists()

        except Exception as e:
            emit_gui_exception_log("PhoenixControlPanel.launch", e)

    def refresh_lists(self):

        try:
            self.saved_list_widget.clear()

            vcs = VaultCoreSingleton.get()
            dir_store = vcs.get_store("directives")

            directives =  dir_store.get_data()


            for key, val in  directives.items():
                if not isinstance(val, dict):
                    continue
                self.saved_list_widget.addItem(f"{key} :: {val.get('label', key)}")

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

    def delete_saved_directive(self):

        try:
            selected_item = self.saved_list_widget.currentItem()
            if not selected_item:
                QMessageBox.warning(self, "No Selection", "Select a saved directive to delete.")
                return

            entry = selected_item.text()
            directive_id = entry.split("::")[0].strip()
            if not directive_id.startswith("directive_"):
                QMessageBox.warning(self, "Invalid Selection", "Directive ID not found.")
                return

            resp = QMessageBox.question(
                self, "Delete Directive",
                f"Are you sure you want to delete {directive_id}? This cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if resp != QMessageBox.StandardButton.Yes:
                return

            vcs = VaultCoreSingleton.get()
            dir_store = vcs.get_store("directives")

            success = dir_store.delete_directive(directive_id)

            if success:
                QMessageBox.information(self, "Deleted", f"Directive {directive_id} deleted.")
            else:
                QMessageBox.warning(self, "Error", f"Failed to delete directive.")

            self.refresh_lists()

        except Exception as e:
            emit_gui_exception_log("DirectiveManagerDialog.delete_saved_directive", e)

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

    def deploy_directive(self):

        try:

            vcs = VaultCoreSingleton.get()

            # step 1. Select directive from vault
            item = self.saved_list_widget.currentItem()
            if not item:
                QMessageBox.warning(self, "No Selection", "Select a saved directive first.")
                return

            directive_id = item.text().split("::")[0].strip()

            vcs = VaultCoreSingleton.get()
            dir_store = vcs.get_store("directives")
            directives = dir_store.get_data()

            directive = directives.get(directive_id)
            if not directive or "json" not in directive:
                QMessageBox.warning(self, "Missing Data", f"Directive '{directive_id}' not found in vault.")
                return

            # step 2. Generate deployment ID and label
            deployment_id = f"{uuid.uuid4().hex[:16]}"
            label, ok = QInputDialog.getText(
                self, "Deployment Label", "Provide a friendly deployment label:",
                text=directive.get("label", "")
            )
            if not ok or not label.strip():
                return

            # step 3. Deepcopy and prepare the directive template
            template_directive = deepcopy(directive["json"])
            agent_aggregator = agent_aggregator_wrapper(template_directive)

            # step 4. Connection assignment via ConnectionAssignmentDialog
            conn_mgr = vcs.get_section("connection_manager")

            # Handle agents from either "agents" or "children"
            if not agent_aggregator.count():
                QMessageBox.warning(self, "No Agents", "No agents found in the deployment directive.")
                return

            wrapped_agents = agent_connection_wrapper(agent_aggregator)

            conn_dlg = ConnectionAssignmentDialog(self, wrapped_agents, conn_mgr)
            if conn_dlg.exec() == QDialog.DialogCode.Accepted:
                conn_dlg.apply_assignments()
            else:
                QMessageBox.warning(self, "No Assignments", "Connection assignments required.")
                return

            wrapped_agents = agent_cert_wrapper(agent_aggregator)
            #inject certs
            EventBus.emit("crypto.service.connection_cert.injector", wrapped_agents)

            wrapped_agents = agent_signing_cert_wrapper(agent_aggregator)
            #inject signing keys
            EventBus.emit("crypto.service.signing_cert.injector", wrapped_agents)

            wrapped_agents = agent_symmetric_encryption_wrapper(agent_aggregator)
            # inject signing keys
            EventBus.emit("crypto.service.symmetric_encryption.injector", wrapped_agents)

            wrapped_agents = agent_directive_wrapper(agent_aggregator)

            try:
                # step 5. Mint the final runtime directive (from template + deployment)
                directive_staging = mint_directive_for_deployment(template_directive, wrapped_agents, deployment_id)
            except Exception as e:
                emit_gui_exception_log("DirectiveManagerDialog.deploy_directive.mint_directive_for_deployment", e)




            #### HERE DOWN NEW DEPLOYMENT PIPELINE USING SWARM





            #FOR RAILGUN SUPPORT
            ssh_map=None
            try:
                ssh_map = deepcopy(conn_mgr.get("ssh", {}))
            except Exception as e:
                pass

            # step 6. Options Dialog (Clown Car, Hashbang)
            opts_dialog = DeployOptionsDialog(ssh_map, label)
            if opts_dialog.exec() != QDialog.DialogCode.Accepted:
                QMessageBox.information(self, "Cancelled", "Deployment process cancelled by operator.")
                return
            opts = opts_dialog.get_options()

            # --- step 7. Agent source embedding (Clown Car) ---
            """
            Handles the "Clown Car" step in the deployment process by verifying and managing the agent source directory
            used in the directive staging process. Supports caching and verifying agent paths, loading or validating from 
            the vault, and ensuring necessary files are available for deployment.

            Steps:
            1. **Check 'Clown Car' Option:**
               - Determines if the "Clown Car" mode is enabled based on the `opts["clown_car"]` flag.
               - Affects how the directive is processed and staged.

            2. **Verify Agent Path:**
               - If the "Clown Car" mode is enabled, attempts to load the last cached agent path from the vault.
               - Verifies if the cached path exists and contains all required sources for the directive.

            3. **Cache Validation:**
               - If the cached path is invalid or missing necessary files, opens a verification dialog (`AgentRootCheckDialog`) 
                 for the user to select and verify the correct agent source directory.
               - Caches the newly verified path in `self.vault_data` for future deployments.

            4. **Generate Encrypted Directive:**
               - Calls `generate_swarm_encrypted_directive` to bundle the directive data along with encryption, 
                 integrating the verified agent path if applicable.

            
            Functions/Methods:
                AgentRootSelector.resolve_agents_root(agent_path): Resolves the root directory of the agent sources.
                AgentRootSelector.verify_all_sources(directive_staging, agents_root): Verifies all required agent sources 
                    exist for the directive staging at the specified root.
                generate_swarm_encrypted_directive(directive_staging, clown_car, hashbang, base_path): Generates an encrypted 
                    directive based on the provided staging data and configuration.

            Classes/Dialogs:
                AgentRootCheckDialog: Handles user interaction for verifying and selecting the agent root directory, 
                if no valid cached path exists.
         
            """
            clown_car = bool(opts.get("clown_car", False))
            hashbang = clown_car

            if clown_car:

                # Load last cached agent path from vault if available
                agent_path = vcs.data.get("last_agent_path")

                verified_path = None
                if agent_path and Path(agent_path).exists():
                    try:
                        agents_root = AgentRootSelector.resolve_agents_root(agent_path)
                        missing = AgentRootSelector.verify_all_sources(directive_staging, str(agents_root))
                        if not missing:
                            verified_path = str(agents_root)
                            print(f"[CLOWN-CAR] Cached agent path verified: {verified_path}")
                        else:
                            print(f"[CLOWN-CAR][WARN] Cached path missing agents: {missing}")
                    except Exception as e:
                        print(f"[CLOWN-CAR][ERROR] Failed to validate cached path: {e}")

                # If cache invalid or missing, open verification dialog
                if not verified_path:
                    dlg = AgentRootCheckDialog(directive_staging, parent=self)
                    verified_path = dlg.exec_check()

                    if not verified_path:
                        QMessageBox.warning( self, "Cancelled", "Deployment cancelled — agent source directory required.")
                        return

                    # Cache the verified path for next deployment
                    vcs.data["last_agent_path"] = verified_path
                    vcs.patch("last_agent_path", verified_path)
                    print(f"[CLOWN-CAR] Agent root cached: {verified_path}")

                agent_path = verified_path
            else:
                agent_path = None

            bundle, aes_key, directive_hash = generate_swarm_encrypted_directive(directive_staging, clown_car, hashbang, base_path=agent_path)

            # step 8. Preview the newly minted directive (only once)
            staging_dialog = EncryptionStagingDialog(json.dumps(directive_staging, indent=2), self)
            if staging_dialog.exec() != QDialog.DialogCode.Accepted:
                QMessageBox.information(self, "Cancelled", "Directive encryption cancelled by operator.")
                return

            # step 9. Choose save location (default under /deploy/)
            cwd = Path.cwd()  # This is your working directory (repo root if you launch Phoenix there)
            deploy_dir = cwd / "boot_directives"
            deploy_dir.mkdir(parents=True, exist_ok=True)

            keys_dir = deploy_dir / "keys"
            keys_dir.mkdir(parents=True, exist_ok=True)

            universe = f"{label.strip()}"

            universe_temp=opts.get("universe", False)
            railgun_enabled = bool(opts.get("railgun_enabled", False))
            if universe_temp and railgun_enabled:
                universe=universe_temp.strip()

            out_path = deploy_dir / f"{universe}.enc.json"
            key_path = keys_dir / f"{universe}.key"

            # Directive path
            write_encrypted_bundle_to_file(bundle, out_path)

            # Swarm key path
            if not bool(opts.get("railgun_enabled", False)):
                # Only save to disk if Railgun is NOT used
                print(f"[DEPLOY] Writing swarm key to {key_path}")
                with open(key_path, "w", encoding="utf-8") as f:
                    f.write(base64.b64encode(aes_key).decode())
                os.chmod(key_path, 0o600)
            else:
                # Keep swarm key only in memory
                swarm_key_mem = base64.b64encode(aes_key).decode()
                print("[DEPLOY] Railgun active — swarm key held in memory only.")

            # step 10. Update deployment record in the vault with encryption details
            with open(out_path, "rb") as f:
                encrypted_hash = hashlib.sha256(f.read()).hexdigest()

            deployment_record = mint_deployment_metadata(
                template_directive=template_directive,
                wrapped_agents=wrapped_agents,
                deployment_id=deployment_id,
                label=label.strip(),
                source_directive_id=directive_id,
                aes_key_b64=base64.b64encode(aes_key).decode(),
                encrypted_path=str(out_path),
                encrypted_hash=encrypted_hash,
            )

            # Persist in vault (single write; CRUD is trivial now)
            vcs = VaultCoreSingleton.get()
            deployments = vcs.data.setdefault("deployments", {})
            deployments[deployment_id] = deployment_record
            vcs.patch("deployments", deployments)
            self.refresh_lists()

            # === Optional Rail-Gun Fire ===
            if bool(opts.get("railgun_enabled", False)):
                ssh_cfg = opts.get("railgun_target", None)
                if ssh_cfg:
                    # pass the key directly
                    self._railgun_upload_and_boot(ssh_cfg, out_path, swarm_key_mem, opts)
            else:
                # step 11. Show final deploy command to operator
                deploy_cmd = f"""
                🚀 Your directive has been encrypted and saved.
    
                Directive: {out_path}
                Swarm Key: /matrix/boot_directives/keys/{universe}.key
                
                ⚠️ Secure your swarm key:
                    chmod 600 /matrix/boot_directives/keys/{universe}.key
                
                To deploy from command line, use:
    
                    matrixd boot --universe {universe}
    
                Matrix will automatically resolve the encrypted directive and swarm key.
                """
                DeploymentDialog(deploy_cmd, self).exec()

        except Exception as e:
            print(f"Failed directive creation: {e}")
            QMessageBox.critical(self, "Error", f"Deployment error alert:\n{e}")

        # -------------------------------------------------

    def _railgun_upload_and_boot(self, ssh_meta, local_bundle, swarm_key_b64, opts):
        """Upload directive, inject swarm key via env var, stream live deploy output."""
        try:

            host = ssh_meta.get("host")
            user = ssh_meta.get("username")
            port = int(ssh_meta.get("port", 22))
            privkey_pem = ssh_meta.get("private_key")

            try:

                # === Railgun Live Deploy Popup ===
                dlg = QtWidgets.QDialog(self)
                dlg.setWindowTitle(f"Railgun Deploy: {host}")
                dlg.resize(800, 500)

                layout = QtWidgets.QVBoxLayout(dlg)
                output_box = QtWidgets.QTextEdit()
                output_box.setReadOnly(True)
                output_box.setStyleSheet(
                    "background:#000; color:#00ff00; font-family: Consolas, monospace; font-size:12px;"
                )
                layout.addWidget(output_box)

                dlg.show()
                QtWidgets.QApplication.processEvents()
                output_box.append("[RAILGUN] 🔴 LIVE DEPLOY STREAM 🔴")
            except Exception as e:
                QMessageBox.critical(self, "Railgun Deploy Popup", str(e))
                print(f"[RAILGUN][ERROR] Railgun Deploy Popup Error: {e}")

            key = paramiko.RSAKey.from_private_key(io.StringIO(privkey_pem))
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(host, port=port, username=user, pkey=key)
            sftp = client.open_sftp()

            remote_root = "/matrix/boot_directives"
            sftp.mkdir(remote_root) if not self._remote_exists(sftp, remote_root) else None
            remote_bundle = posixpath.join(remote_root, ntpath.basename(local_bundle))
            sftp.put(local_bundle, remote_bundle)
            sftp.close()

            universe = opts.get("universe")
            boot_flags = []
            if opts.get("reboot"): boot_flags.append("--reboot")
            if opts.get("verbose"): boot_flags.append("--verbose")
            if opts.get("debug"): boot_flags.append("--debug")
            if opts.get("rug_pull"): boot_flags.append("--rug-pull")
            if opts.get("clean"): boot_flags.append("--clean")
            if opts.get("reboot_new"): boot_flags.append("--reboot-new")
            if opts.get("reboot_id"): boot_flags.append(f"--reboot-id {opts['reboot_id']}")
            boot_flags_str = " ".join(boot_flags)

            # Safe inline export – invisible to ps
            swarm_key = swarm_key_b64.strip()
            cmd = (
                f"cd /matrix && "
                f"export SITE_ROOT=/matrix && "
                f"export SWARM_KEY='{swarm_key}' && "
                f"[ -d /matrix/venv ] && source /matrix/venv/bin/activate || echo '[RAILGUN] No venv detected' && "
                f"(matrixd boot --universe {universe} --directive {remote_bundle} {boot_flags_str}) "
                f"2>&1 | tee /matrix/railgun_deploy.log"
            )

            print(f"[RAILGUN] Executing remote deploy on {host}...")

            # Create a live PTY channel for real-time output
            transport = client.get_transport()
            channel = transport.open_session()
            channel.get_pty()
            channel.exec_command(cmd)


            QtWidgets.QApplication.processEvents()
            while True:
                if channel.recv_ready():

                    chunk = channel.recv(4096).decode(errors="ignore")
                    try:
                        output_box.append(chunk)
                    except Exception as e:
                        pass

                    QtWidgets.QApplication.processEvents()
                if channel.recv_stderr_ready():

                    try:
                        err = channel.recv_stderr(4096).decode(errors="ignore")
                        output_box.append(f"<span style='color:red'>{err}</span>")
                    except Exception as e:
                        pass

                    QtWidgets.QApplication.processEvents()
                if channel.exit_status_ready():
                    break

            exit_code = channel.recv_exit_status()
            output_box.append(f"\n[RAILGUN] Deploy finished (exit={exit_code})")
            QtWidgets.QApplication.processEvents()

        except Exception as e:
            QMessageBox.critical(self, "Railgun Failed", str(e))
            print(f"[RAILGUN][ERROR] {e}")
        finally:
            try:
                client.close()
                dlg.exec()  # keep window open until closed
            except Exception as e:
                pass

    def _remote_exists(self, sftp, path):
        try:
            sftp.stat(path)
            return True
        except FileNotFoundError:
            return False

